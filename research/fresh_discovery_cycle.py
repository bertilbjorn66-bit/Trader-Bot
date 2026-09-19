from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import research.enriched_conditional_experiment as experiment
from research.datafeed_empirical import PAIR_TO_SYMBOL, load_feed_bars
from research.enriched_conditional_experiment import EvalResult, TargetRecord, assign_global_split
from research.execution import ExecutionAssumptions
from research.sequential_empirical import DEFAULT_HORIZONS


# Stage 21 is intentionally discovery-only: confirmation remains a separate frozen gate.
DISCOVERY_CONTRACT_VERSION = "v4-global-horizon-aware-two-stage-screen"
AGREEMENT_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75)
DISTANCE_GRID: tuple[float | None, ...] = (None, 0.5, 1.0, 1.5, 2.0)
REGIMES = (
    "regime:breakout_up",
    "regime:breakout_down",
    "regime:high_vol_trend_up",
    "regime:high_vol_trend_down",
    "regime:high_volatility_range",
    "regime:trend_up",
    "regime:trend_down",
    "regime:range_low_vol",
    "regime:range_normal",
)
SESSIONS = ("asia", "london", "new_york", "overlap")
PAIRSETS = ("all", "JPY")
DIRECTIONS = ("long", "short")
MIN_DISCOVERY_SAMPLES = 150
MIN_DISCOVERY_PF = 1.10
MIN_DISCOVERY_BOOTSTRAP_LOWER = 0.0
TOP_N = 25
DISCOVERY_HOLM_ALPHA = 0.05


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discovery_result_is_admissible(result: EvalResult | None) -> bool:
    """Apply the discovery-only statistical screen before candidate ranking."""
    if result is None or result["n"] < MIN_DISCOVERY_SAMPLES:
        return False
    pf = result["profit_factor"]
    lower = result["bootstrap_expectancy_ci_pips"][0]
    return pf is not None and pf >= MIN_DISCOVERY_PF and lower is not None and lower > MIN_DISCOVERY_BOOTSTRAP_LOWER


def _candidate_key(candidate: dict[str, Any]) -> tuple[float, float, float, int]:
    discovery = candidate["discovery"]
    bootstrap_low = discovery.get("bootstrap_expectancy_ci_pips", [None, None])[0]
    return (
        float(bootstrap_low if bootstrap_low is not None else -math.inf),
        float(discovery["profit_factor"] or -math.inf),
        float(discovery["expectancy_pips"]),
        int(discovery["n"]),
    )


def _group_discovery_records(
    records: list[TargetRecord],
) -> dict[tuple[int, str, str, str, str, str], list[TargetRecord]]:
    grouped: dict[tuple[int, str, str, str, str, str], list[TargetRecord]] = {}
    for record in records:
        if record["global_split"] != "discovery":
            continue
        base_key = (
            int(record["horizon"]),
            str(record["regime"]),
            str(record["session"]),
            str(record["direction"]),
            "discovery",
        )
        grouped.setdefault((*base_key, "all"), []).append(record)
        if record["pair"].endswith("/JPY"):
            grouped.setdefault((*base_key, "JPY"), []).append(record)
    return grouped


def _analyze_pair_from_feed(
    pair: str,
    feed_path: str,
    sample_stride: int,
    history_states: int,
    costs: ExecutionAssumptions,
) -> tuple[str, list[TargetRecord], dict[str, object]]:
    records, pair_quality = experiment.analyze_pair(
        pair,
        load_feed_bars(Path(feed_path)),
        sample_stride,
        history_states,
        costs,
    )
    return pair, records, pair_quality


def run_discovery(input_dir: Path, sample_stride: int, history_states: int, parallel_workers: int = 1) -> dict[str, Any]:
    if sample_stride <= 0 or history_states <= 0 or parallel_workers <= 0:
        raise ValueError("sample_stride, history_states, and parallel_workers must be positive")

    costs = ExecutionAssumptions()
    all_records: list[TargetRecord] = []
    quality: dict[str, Any] = {}
    source_manifest: dict[str, Any] = {}
    feed_jobs: list[tuple[str, Path]] = []
    for pair in PAIR_TO_SYMBOL:
        feed_path = input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"
        source_manifest[pair] = {
            "path": str(feed_path),
            "sha256": _sha256_file(feed_path),
        }
        feed_jobs.append((pair, feed_path))

    if parallel_workers <= 1:
        results = [
            _analyze_pair_from_feed(pair, str(feed_path), sample_stride, history_states, costs)
            for pair, feed_path in feed_jobs
        ]
    else:
        with ProcessPoolExecutor(max_workers=parallel_workers) as executor:
            results = list(
                executor.map(
                    _analyze_pair_from_feed,
                    [pair for pair, _feed_path in feed_jobs],
                    [str(feed_path) for _pair, feed_path in feed_jobs],
                    [sample_stride] * len(feed_jobs),
                    [history_states] * len(feed_jobs),
                    [costs] * len(feed_jobs),
                )
            )

    by_pair = {pair: (records, pair_quality) for pair, records, pair_quality in results}
    for pair in PAIR_TO_SYMBOL:
        records, pair_quality = by_pair[pair]
        all_records.extend(records)
        quality[pair] = pair_quality

    global_split_cutoff = assign_global_split(all_records)

    family_hypotheses: list[dict[str, Any]] = []
    bootstrap_near_misses: list[dict[str, Any]] = []
    bootstrap_screened = 0
    discovery_search_started = time.perf_counter()

    grouped_records = _group_discovery_records(all_records)

    for horizon in DEFAULT_HORIZONS:
        for agreement_min in AGREEMENT_GRID:
            for distance_max in DISTANCE_GRID:
                for regime in REGIMES:
                    for session in SESSIONS:
                        for pairset in PAIRSETS:
                            for direction in DIRECTIONS:
                                subset = grouped_records.get(
                                    (horizon, regime, session, direction, "discovery", pairset),
                                    [],
                                )
                                cheap = experiment.evaluate(
                                    subset,
                                    distance_max,
                                    agreement_min,
                                    "discovery",
                                    with_bootstrap=False,
                                )
                                if cheap is None or cheap["n"] < MIN_DISCOVERY_SAMPLES:
                                    continue

                                values = experiment.filtered_outcomes(
                                    subset,
                                    distance_max,
                                    agreement_min,
                                    "discovery",
                                )
                                if len(values) != cheap["n"]:
                                    raise RuntimeError("candidate filtering and evaluator sample counts diverged")
                                raw_hac_pvalue = hac_mean_pvalue(values)

                                candidate: dict[str, Any] = {
                                    "horizon": horizon,
                                    "agreement_min": agreement_min,
                                    "distance_max": distance_max,
                                    "regime": regime,
                                    "session": session,
                                    "pairset": pairset,
                                    "direction": direction,
                                    "discovery": cheap,
                                }
                                family_hypotheses.append({
                                    "candidate": candidate,
                                    "raw_hac_one_sided_pvalue": raw_hac_pvalue,
                                    "profit_factor_pass": (
                                        cheap["profit_factor"] is not None
                                        and cheap["profit_factor"] >= MIN_DISCOVERY_PF
                                    ),
                                    "bootstrap_pass": False,
                                    "bootstrap": None,
                                })

                                if not family_hypotheses[-1]["profit_factor_pass"]:
                                    continue
                                if raw_hac_pvalue > DISCOVERY_HOLM_ALPHA:
                                    continue

                                bootstrap = experiment.evaluate(
                                    subset,
                                    distance_max,
                                    agreement_min,
                                    "discovery",
                                    with_bootstrap=True,
                                )
                                bootstrap_screened += 1
                                family_hypotheses[-1]["bootstrap"] = bootstrap
                                if discovery_result_is_admissible(bootstrap):
                                    family_hypotheses[-1]["bootstrap_pass"] = True

    family_adjusted_pvalues = holm_bonferroni(
        [float(item["raw_hac_one_sided_pvalue"]) for item in family_hypotheses]
    )
    candidates: list[dict[str, Any]] = []
    for item, adjusted_pvalue in zip(family_hypotheses, family_adjusted_pvalues, strict=True):
        candidate = dict(item["candidate"])
        bootstrap = item["bootstrap"]
        raw_pvalue = float(item["raw_hac_one_sided_pvalue"])
        candidate["discovery_hac_one_sided_pvalue"] = raw_pvalue
        candidate["discovery_hac_holm_adjusted_pvalue"] = adjusted_pvalue
        candidate["discovery_family_size"] = len(family_hypotheses)
        if (
            bool(item["profit_factor_pass"])
            and bool(item["bootstrap_pass"])
            and adjusted_pvalue <= DISCOVERY_HOLM_ALPHA
        ):
            if bootstrap is None:
                raise RuntimeError("bootstrap result missing for admissible discovery candidate")
            candidate["discovery"] = bootstrap
            candidates.append(candidate)
        elif bool(item["profit_factor_pass"]) and bootstrap is not None:
            near_miss = dict(candidate)
            near_miss["discovery"] = bootstrap
            near_miss["near_miss_reason"] = (
                "failed discovery-family Holm-adjusted HAC p-value"
                if adjusted_pvalue > DISCOVERY_HOLM_ALPHA
                else "failed discovery bootstrap lower-tail admission"
            )
            bootstrap_near_misses.append(near_miss)

    candidates.sort(key=_candidate_key, reverse=True)
    bootstrap_near_misses.sort(key=_candidate_key, reverse=True)
    selected = candidates[:TOP_N]
    return {
        "status": "FRESH_DISCOVERY_COMPLETED",
        "selection_policy": {
            "contract_version": DISCOVERY_CONTRACT_VERSION,
            "source": "verified nine-pair historical feed",
            "split": "global horizon-aware chronological discovery segment across all nine pairs",
            "minimum_discovery_samples": MIN_DISCOVERY_SAMPLES,
            "minimum_discovery_profit_factor": MIN_DISCOVERY_PF,
            "minimum_discovery_bootstrap_lower_expectancy_pips": MIN_DISCOVERY_BOOTSTRAP_LOWER,
            "candidate_grid": {
                "horizons": list(DEFAULT_HORIZONS),
                "agreement_min": list(AGREEMENT_GRID),
                "distance_max": list(DISTANCE_GRID),
                "regimes": list(REGIMES),
                "sessions": list(SESSIONS),
                "pairsets": list(PAIRSETS),
                "directions": list(DIRECTIONS),
            },
            "ranking": "discovery bootstrap lower 95% expectancy, then discovery profit factor, then discovery expectancy, then sample count",
            "discovery_familywise_control": "one-sided HAC mean p-values for every selectable discovery hypothesis (n>=150) followed by Holm correction across the entire selectable family",
            "discovery_family_holm_alpha": DISCOVERY_HOLM_ALPHA,
            "discovery_family_size": len(family_hypotheses),
            "two_stage_screen": "sample/PF evaluated first; HAC family p-value computed for every selectable hypothesis; bootstrap lower-tail computed only for PF and raw-p<=alpha survivors; final selection also requires Holm-adjusted HAC p<=alpha; no threshold relaxed",
            "bootstrap_screened_candidate_count": bootstrap_screened,
            "bootstrap_near_miss_count": len(bootstrap_near_misses),
            "bootstrap_near_miss_policy": "diagnostic only; near-misses never enter candidate selection or confirmation",
            "bootstrap_near_miss_reasons": "failed bootstrap lower-tail admission and/or discovery-family Holm-adjusted HAC p-value",
            "confirmation_used_for_selection": False,
            "prior_frozen_confirmation_artifact_read": False,
            "time_continuity": "exact 10-minute continuity is enforced in state, analogue, and target windows by the research engine",
            "split_assignment": "global cutoff over all target timestamps; a target is discovery only when its complete target outcome ends strictly before the cutoff",
            "parallel_workers": parallel_workers,
            "discovery_search_seconds": time.perf_counter() - discovery_search_started,
            "grouped_record_key": "(horizon, regime, session, direction, split, pairset)",
        },
        "record_count": len(all_records),
        "global_split_cutoff": global_split_cutoff,
        "source_manifest": source_manifest,
        "candidate_count": len(candidates),
        "top_candidates": selected,
        "bootstrap_near_misses": bootstrap_near_misses[:TOP_N],
        "data_quality": quality,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fresh discovery-only conditional-edge search.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--parallel-workers", type=int, default=2)
    args = parser.parse_args()

    report = run_discovery(Path(args.input_dir), args.sample_stride, args.history_states, args.parallel_workers)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
