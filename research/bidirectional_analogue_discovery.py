from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from math import inf
from pathlib import Path
from statistics import mean, median
from typing import Any, Sequence

from research.cross_section import session_label
from research.datafeed_empirical import PAIR_TO_SYMBOL, _execution_valid_rows, _market_bars, load_feed_bars
from research.enriched_conditional_experiment import TargetRecord, assign_global_split
from research.execution import ExecutionAssumptions, net_move
from research.multiple_testing import holm_bonferroni
from research.non_live_evaluation import block_bootstrap_means, bootstrap_means, profit_factor
from research.pipeline import state_from_bar_window
from research.regimes import classify_regime
from research.similarity import DEFAULT_FEATURES, SimilarityIndex
from research.statistics import hac_mean_pvalue
from research.types import Bar, State

PAIR_PIP = {
    "EUR/USD": 0.0001,
    "GBP/USD": 0.0001,
    "USD/JPY": 0.01,
    "AUD/USD": 0.0001,
    "USD/CAD": 0.0001,
    "USD/CHF": 0.0001,
    "NZD/USD": 0.0001,
    "EUR/JPY": 0.01,
    "GBP/JPY": 0.01,
}

CONTRACT_VERSION = "v1-bidirectional-analogue-familywise"
EXPECTED_BAR_INTERVAL = timedelta(minutes=10)
HORIZONS = (1, 2, 3, 6)
K_VALUES = (25, 50, 100)
MAX_K = max(K_VALUES)
MIN_DISCOVERY_SAMPLES = 150
MIN_DISCOVERY_PF = 1.10
MIN_DISCOVERY_BOOTSTRAP_LOWER = 0.0
MIN_POSITIVE_PAIRS = 3
MIN_PAIR_SAMPLES = 20
MAX_PAIR_OBSERVATION_SHARE = 0.80
BOOTSTRAP_REPS = 2000
BOOTSTRAP_BLOCK_SIZE = 5
HOLM_ALPHA = 0.05


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_contiguous_window(bars: list[Bar], start: int, end: int) -> bool:
    if start < 0 or end >= len(bars) or start > end:
        return False
    return all(
        (current.timestamp - previous.timestamp) == EXPECTED_BAR_INTERVAL
        for previous, current in zip(bars[start:end], bars[start + 1 : end + 1], strict=True)
    )


def _stats(values: list[float]) -> dict[str, float | int | None]:
    wins = [value for value in values if value > 0.0]
    return {
        "n": len(values),
        "expectancy_pips": mean(values) if values else None,
        "profit_factor": profit_factor(values),
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_pips": _max_drawdown(values),
    }


def _max_drawdown(values: list[float]) -> float:
    balance = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        balance += value
        peak = max(peak, balance)
        worst = min(worst, balance - peak)
    return abs(worst)


def _pair_breakdown(records: Sequence[Mapping[str, object]]) -> dict[str, dict[str, float | int | None]]:
    grouped: dict[str, list[float]] = {}
    for record in records:
        grouped.setdefault(str(record["pair"]), []).append(float(record["outcome_pips"]))
    return {pair: _stats(values) for pair, values in sorted(grouped.items())}


def _robust_discovery_record_set(records: Sequence[Mapping[str, object]]) -> bool:
    pairs = _pair_breakdown(records)
    eligible = {
        pair: result
        for pair, result in pairs.items()
        if int(result["n"]) >= MIN_PAIR_SAMPLES
    }
    positive = {
        pair: result
        for pair, result in eligible.items()
        if result["expectancy_pips"] is not None
        and result["expectancy_pips"] > 0.0
        and (
            result["profit_factor"] is None
            or result["profit_factor"] > 1.0
        )
    }
    largest_share = max(
        (int(result["n"]) / len(records) for result in pairs.values()),
        default=1.0,
    )
    return (
        len(positive) >= MIN_POSITIVE_PAIRS
        and largest_share <= MAX_PAIR_OBSERVATION_SHARE
    )


def _bootstrap(values: list[float], seed: int) -> dict[str, float]:
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=seed)
    block = block_bootstrap_means(
        values,
        block_size=min(BOOTSTRAP_BLOCK_SIZE, len(values)),
        reps=BOOTSTRAP_REPS,
        seed=seed + 1,
    )
    return {
        "ordinary_lower_95_mean": ordinary[49],
        "ordinary_upper_95_mean": ordinary[-50],
        "block_lower_95_mean": block[49],
        "block_upper_95_mean": block[-50],
        "ordinary_probability_positive_mean": mean(value > 0.0 for value in ordinary),
    }


def _analyze_pair(
    pair: str,
    rows: list[dict[str, object]],
    sample_stride: int,
    history_states: int,
    costs: ExecutionAssumptions,
) -> tuple[list[TargetRecord], dict[str, object]]:
    rows, quality = _execution_valid_rows(rows, pair)
    bid, ask = _market_bars(rows)
    bars = empirical._merge(bid, ask)
    if len(bars) < empirical.STATE_LOOKBACK + history_states + max(HORIZONS) + 10:
        raise ValueError(f"insufficient bars for {pair}")

    states: list[State] = []
    state_index: dict[datetime, int] = {}
    for index in range(empirical.STATE_LOOKBACK, len(bars)):
        if not _is_contiguous_window(
            bars,
            index - empirical.STATE_LOOKBACK,
            index,
        ):
            continue
        state = state_from_bar_window(bars, index, empirical.STATE_LOOKBACK)
        states.append(state)
        state_index[state.timestamp] = index

    similarity = SimilarityIndex(states, DEFAULT_FEATURES)
    targets: list[TargetRecord] = []

    for position in range(history_states, len(states), sample_stride):
        target = states[position]
        target_index = state_index[target.timestamp]
        if not _is_contiguous_window(bars, target_index, target_index + max(HORIZONS)):
            continue

        history_start = position - history_states
        history = states[history_start:position]
        scaler = similarity.fit_scaler(history_start, position)
        nearest = similarity.nearest(
            target,
            history_start,
            position,
            scaler,
            k=min(MAX_K, len(history)),
        )
        eligible: list[tuple[State, float, int]] = []
        for neighbour, distance in nearest:
            index = state_index[neighbour.timestamp]
            if index + max(HORIZONS) >= target_index:
                continue
            if not _is_contiguous_window(bars, index, index + max(HORIZONS)):
                continue
            eligible.append((neighbour, distance, index))

        if len(eligible) < max(K_VALUES):
            continue

        for horizon in HORIZONS:
            long_values: list[float] = []
            short_values: list[float] = []
            target_end_index = target_index + horizon
            if target_end_index >= len(bars):
                continue
            if not _is_contiguous_window(bars, target_index, target_end_index):
                continue

            for _neighbour, _distance, index in eligible[:MAX_K]:
                long_outcome = empirical_outcome(bars, index, horizon, "long")
                short_outcome = empirical_outcome(bars, index, horizon, "short")
                long_values.append(
                    net_move(long_outcome.return_abs, costs) / PAIR_PIP[pair]
                )
                short_values.append(
                    net_move(short_outcome.return_abs, costs) / PAIR_PIP[pair]
                )

            for k in K_VALUES:
                decision = decide_direction(long_values, short_values, k)
                if decision is None:
                    continue
                direction, predicted, decision_margin = decision
                long_mean = mean(long_values[:k])
                short_mean = mean(short_values[:k])

                target_outcome = empirical_outcome(
                    bars,
                    target_index,
                    horizon,
                    direction,
                )
                outcome_pips = net_move(target_outcome.return_abs, costs) / PAIR_PIP[pair]
                nearest_distances = [distance for _, distance, _ in eligible[:k]]
                chosen_values = long_values[:k] if direction == "long" else short_values[:k]
                targets.append(
                    {
                        "pair": pair,
                        "timestamp": target.timestamp.isoformat(),
                        "year": target.timestamp.year,
                        "session": session_label(target.timestamp),
                        "regime": (
                            "regime:"
                            + classify_regime(
                                float(target.features.get("trend") or 0.0),
                                float(target.features.get("trend_strength") or 0.0),
                                empirical._volatility_z(target, history),
                                int(target.features.get("breakout") or 0),
                            )
                        ),
                        "direction": direction,
                        "horizon": horizon,
                        "k": k,
                        "agreement": sum(value > 0.0 for value in chosen_values) / k,
                        "median_distance": median(nearest_distances),
                        "distance_p10": None,
                        "distance_p90": None,
                        "outcome_pips": outcome_pips,
                        "split": "",
                        "target_end_timestamp": bars[target_end_index].timestamp.isoformat(),
                        "global_split": "",
                        "predicted_direction_mean_pips": predicted,
                        "long_direction_mean_pips": long_mean,
                        "short_direction_mean_pips": short_mean,
                        "decision_margin_pips": decision_margin,
                    }
                )

    timestamps = sorted(
        datetime.fromisoformat(record["timestamp"])
        for record in targets
    )
    local_cutoff = timestamps[int(len(timestamps) * 0.60)] if timestamps else None
    for record in targets:
        timestamp = datetime.fromisoformat(record["timestamp"])
        record["split"] = (
            "discovery" if local_cutoff and timestamp < local_cutoff else "confirmation"
        )
    return targets, quality


def empirical_outcome(
    bars: list[Bar],
    index: int,
    horizon: int,
    direction: str,
):
    return empirical.future_outcome(bars, index, horizon, direction)


def decide_direction(
    long_values: list[float],
    short_values: list[float],
    k: int,
) -> tuple[str, float, float] | None:
    if k <= 0 or len(long_values) < k or len(short_values) < k:
        raise ValueError("direction decision requires k available observations")
    long_mean = mean(long_values[:k])
    short_mean = mean(short_values[:k])
    margin = abs(long_mean - short_mean)
    if long_mean == short_mean:
        return None
    predicted = max(long_mean, short_mean)
    if predicted <= 0.0:
        return None
    return ("long" if long_mean > short_mean else "short", predicted, margin)


def _candidate_identity(horizon: int, k: int) -> dict[str, int]:
    return {"horizon": horizon, "k": k}


def candidate_fingerprint(candidate: dict[str, int]) -> str:
    payload = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _analyze_pair_from_path(
    pair: str,
    path: Path,
    sample_stride: int,
    history_states: int,
    costs: ExecutionAssumptions,
) -> tuple[list[TargetRecord], dict[str, object]]:
    return _analyze_pair(
        pair,
        load_feed_bars(path),
        sample_stride,
        history_states,
        costs,
    )


def run_discovery(
    input_dir: Path,
    sample_stride: int,
    history_states: int,
    parallel_workers: int = 1,
) -> dict[str, object]:
    if sample_stride <= 0 or history_states <= 0 or parallel_workers <= 0:
        raise ValueError("sample_stride, history_states, and parallel_workers must be positive")

    costs = ExecutionAssumptions()
    source_manifest: dict[str, object] = {}
    jobs: list[tuple[str, Path]] = []
    for pair in PAIR_TO_SYMBOL:
        path = input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"
        source_manifest[pair] = {"path": str(path), "sha256": _sha256_file(path)}
        jobs.append((pair, path))

    results: list[tuple[list[TargetRecord], dict[str, object]]] = []
    if parallel_workers == 1:
        for pair, path in jobs:
            results.append(
                _analyze_pair_from_path(
                    pair,
                    path,
                    sample_stride,
                    history_states,
                    costs,
                )
            )
    else:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=parallel_workers) as executor:
            results = list(
                executor.map(
                    _analyze_pair_from_path,
                    [pair for pair, _path in jobs],
                    [path for _pair, path in jobs],
                    [sample_stride] * len(jobs),
                    [history_states] * len(jobs),
                    [costs] * len(jobs),
                )
            )

    all_records: list[TargetRecord] = []
    quality: dict[str, object] = {}
    for (pair, _path), (records, pair_quality) in zip(jobs, results, strict=True):
        all_records.extend(records)
        quality[pair] = pair_quality

    global_split_cutoff = assign_global_split(all_records)
    family: list[dict[str, Any]] = []

    for horizon in HORIZONS:
        for k in K_VALUES:
            records = sorted(
                [
                    record
                    for record in all_records
                    if record["global_split"] == "discovery"
                    and int(record["horizon"]) == horizon
                    and int(record["k"]) == k
                ],
                key=lambda record: (record["timestamp"], record["pair"]),
            )
            stats = _stats([float(record["outcome_pips"]) for record in records])
            if int(stats["n"]) < MIN_DISCOVERY_SAMPLES:
                continue
            values = [float(record["outcome_pips"]) for record in records]
            raw_pvalue = hac_mean_pvalue(values)
            pair_robust = _robust_discovery_record_set(records)
            item: dict[str, Any] = {
                "candidate": _candidate_identity(horizon, k),
                "candidate_fingerprint": candidate_fingerprint(_candidate_identity(horizon, k)),
                "n": int(stats["n"]),
                "statistics": stats,
                "raw_hac_one_sided_pvalue": raw_pvalue,
                "pair_robust": pair_robust,
                "bootstrap": None,
                "bootstrap_pass": False,
            }
            if (
                stats["profit_factor"] is not None
                and float(stats["profit_factor"]) >= MIN_DISCOVERY_PF
                and raw_pvalue <= HOLM_ALPHA
                and pair_robust
            ):
                bootstrap = _bootstrap(values, 2026092001 + horizon * 100 + k)
                item["bootstrap"] = bootstrap
                item["bootstrap_pass"] = (
                    bootstrap["ordinary_lower_95_mean"] > MIN_DISCOVERY_BOOTSTRAP_LOWER
                    and bootstrap["block_lower_95_mean"] > MIN_DISCOVERY_BOOTSTRAP_LOWER
                )
            family.append(item)

    adjusted = holm_bonferroni(
        [float(item["raw_hac_one_sided_pvalue"]) for item in family]
    )
    candidates: list[dict[str, Any]] = []
    near_misses: list[dict[str, Any]] = []
    for item, adjusted_pvalue in zip(family, adjusted, strict=True):
        candidate = dict(item["candidate"])
        candidate["candidate_fingerprint"] = item["candidate_fingerprint"]
        candidate["discovery"] = item["statistics"]
        candidate["discovery_hac_one_sided_pvalue"] = item["raw_hac_one_sided_pvalue"]
        candidate["discovery_hac_holm_adjusted_pvalue"] = adjusted_pvalue
        candidate["discovery_family_size"] = len(family)
        if (
            bool(item["pair_robust"])
            and item["statistics"]["profit_factor"] is not None
            and float(item["statistics"]["profit_factor"]) >= MIN_DISCOVERY_PF
            and adjusted_pvalue <= HOLM_ALPHA
            and bool(item["bootstrap_pass"])
        ):
            candidates.append(candidate)
        else:
            near = dict(candidate)
            near["near_miss_reason"] = _near_miss_reason(item, adjusted_pvalue)
            near_misses.append(near)

    candidates.sort(
        key=lambda candidate: (
            float(candidate["discovery"]["expectancy_pips"] or -inf),
            float(candidate["discovery"]["profit_factor"] or -inf),
        ),
        reverse=True,
    )
    return {
        "status": "BIDIRECTIONAL_ANALOGUE_DISCOVERY_COMPLETED",
        "selection_policy": {
            "contract_version": CONTRACT_VERSION,
            "source": "verified nine-pair historical BID/ASK feeds",
            "split": "global horizon-aware chronological discovery segment across all nine pairs",
            "candidate_family": "horizon x k only; direction is learned from pre-target analogue outcomes and is never a searched hyperparameter",
            "horizons": list(HORIZONS),
            "k_values": list(K_VALUES),
            "minimum_discovery_samples": MIN_DISCOVERY_SAMPLES,
            "minimum_discovery_profit_factor": MIN_DISCOVERY_PF,
            "minimum_positive_pairs": MIN_POSITIVE_PAIRS,
            "minimum_pair_samples": MIN_PAIR_SAMPLES,
            "maximum_pair_observation_share": MAX_PAIR_OBSERVATION_SHARE,
            "familywise_control": "one-sided HAC mean p-values for every selectable hypothesis with n>=150 followed by Holm correction across the complete eligible family",
            "familywise_alpha": HOLM_ALPHA,
            "bootstrap_gate": "ordinary and block lower 95% mean both > 0",
            "confirmation_used_for_selection": False,
            "prior_frozen_confirmation_artifact_read": False,
        },
        "candidate_count": len(candidates),
        "top_candidates": candidates[:10],
        "near_misses": near_misses[:25],
        "discovery_family": family,
        "record_count": len(all_records),
        "global_split_cutoff": global_split_cutoff,
        "source_manifest": source_manifest,
        "orchestration_binding": {},
        "data_quality": quality,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def _near_miss_reason(item: dict[str, object], adjusted_pvalue: float) -> str:
    if not bool(item["pair_robust"]):
        return "failed discovery pair-diversity/concentration gate"
    statistics = item["statistics"]
    if statistics["profit_factor"] is None or float(statistics["profit_factor"]) < MIN_DISCOVERY_PF:
        return "failed discovery profit-factor gate"
    if adjusted_pvalue > HOLM_ALPHA:
        return "failed discovery-family Holm-adjusted HAC p-value"
    if not bool(item["bootstrap_pass"]):
        return "failed ordinary/block bootstrap lower-tail gate"
    return "failed unspecified discovery gate"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Leakage-safe bidirectional analogue discovery from verified empirical feeds."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--parallel-workers", type=int, default=4)
    args = parser.parse_args()
    result = run_discovery(
        Path(args.input_dir),
        args.sample_stride,
        args.history_states,
        args.parallel_workers,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"BIDIRECTIONAL_DISCOVERY_STATE={result['status']}")
    print(f"CANDIDATE_COUNT={result['candidate_count']}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
