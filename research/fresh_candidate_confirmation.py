from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

from research import enriched_conditional_experiment as experiment
from research.datafeed_empirical import PAIR_TO_SYMBOL, load_feed_bars
from research.non_live_evaluation import (
    block_bootstrap_means,
    bootstrap_means,
    max_drawdown,
    probability_of_ruin,
    profit_factor,
)
from research.execution import ExecutionAssumptions

MIN_CONFIRMATION_SAMPLES = 100
MIN_PAIR_SAMPLES = 20
FOLDS = 4
STRESS_COSTS_PIPS = (0.0, 0.2, 0.5, 1.0, 1.5)
BOOTSTRAP_REPS = 2000
RUIN_SIMULATIONS = 5000
MAX_PAIR_OBSERVATION_SHARE = 0.80


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def candidate_fingerprint(candidate: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(candidate).encode("utf-8")).hexdigest()


def _matches(record: dict[str, Any], candidate: dict[str, Any], split: str) -> bool:
    return (
        record["split"] == split
        and int(record["horizon"]) == int(candidate["horizon"])
        and record["regime"] == candidate["regime"]
        and record["session"] == candidate["session"]
        and (candidate["pairset"] == "all" or str(record["pair"]).endswith("/JPY"))
        and (
            candidate["distance_max"] is None
            or float(record["median_distance"]) <= float(candidate["distance_max"])
        )
        and float(record["agreement_min"]) <= float(record["agreement"])
    )


def _ordered_values(records: Sequence[dict[str, Any]]) -> list[float]:
    ordered = sorted(records, key=lambda record: datetime.fromisoformat(str(record["timestamp"])))
    return [float(record["outcome_pips"]) for record in ordered]


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "expectancy_pips": None, "profit_factor": None, "win_rate": None, "max_drawdown_pips": None}
    return {
        "n": len(values),
        "expectancy_pips": mean(values),
        "profit_factor": profit_factor(values),
        "win_rate": sum(value > 0 for value in values) / len(values),
        "max_drawdown_pips": max_drawdown(values),
    }


def _folds(values: Sequence[float]) -> list[dict[str, Any]]:
    if len(values) < FOLDS:
        return []
    size = len(values) // FOLDS
    results: list[dict[str, Any]] = []
    for fold_id in range(FOLDS):
        start = fold_id * size
        end = len(values) if fold_id == FOLDS - 1 else (fold_id + 1) * size
        results.append({"fold_id": fold_id, "stats": _stats(values[start:end])})
    return results


def _pair_breakdown(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for record in records:
        grouped.setdefault(str(record["pair"]), []).append(float(record["outcome_pips"]))
    return {pair: _stats(values) for pair, values in sorted(grouped.items())}


def _bootstrap(values: Sequence[float]) -> dict[str, float]:
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=20260826)
    block = block_bootstrap_means(values, block_size=min(5, len(values)), reps=BOOTSTRAP_REPS, seed=20260827)
    return {
        "ordinary_lower_95_mean": ordinary[24],
        "ordinary_upper_95_mean": ordinary[-25],
        "block_lower_95_mean": block[24],
        "block_upper_95_mean": block[-25],
        "probability_positive_mean": mean(value > 0 for value in ordinary),
    }


def evaluate_primary(report: dict[str, Any], records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if report.get("status") != "FRESH_DISCOVERY_COMPLETED":
        raise ValueError("source discovery report is not complete")
    policy = report.get("selection_policy", {})
    if policy.get("confirmation_used_for_selection") is not False:
        raise ValueError("discovery report does not prove confirmation-free selection")
    if policy.get("prior_frozen_confirmation_artifact_read") is not False:
        raise ValueError("discovery report references the prior frozen confirmation artifact")
    candidates = report.get("top_candidates")
    if not isinstance(candidates, list) or not candidates:
        return {"state": "INCOMPLETE", "reason": "fresh discovery produced no candidate", "promotion_authorized": False, "live_execution_authorized": False}

    primary = dict(candidates[0])
    if "confirmation" in primary:
        raise ValueError("discovery candidate already contains confirmation results")
    primary["rank"] = 1
    fingerprint = candidate_fingerprint({key: primary[key] for key in ("horizon", "agreement_min", "distance_max", "regime", "session", "pairset")})

    confirmation = [record for record in records if _matches(record, primary, "confirmation")]
    values = _ordered_values(confirmation)
    if len(values) < MIN_CONFIRMATION_SAMPLES:
        return {
            "state": "INCOMPLETE",
            "reason": "primary candidate confirmation sample is below the predefined minimum",
            "candidate": primary,
            "candidate_fingerprint": fingerprint,
            "confirmation": _stats(values),
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    base = _stats(values)
    folds = _folds(values)
    all_folds_positive = bool(folds) and all(
        fold["stats"]["expectancy_pips"] is not None and fold["stats"]["expectancy_pips"] > 0 for fold in folds
    )
    stress = {
        str(cost): _stats([value - cost for value in values]) for cost in STRESS_COSTS_PIPS
    }
    stress_resilient = all(
        result["expectancy_pips"] is not None
        and result["expectancy_pips"] > 0
        and result["profit_factor"] is not None
        and result["profit_factor"] > 1
        for result in stress.values()
    )

    pairs = _pair_breakdown(confirmation)
    positive_pairs = sum(
        1
        for result in pairs.values()
        if result["n"] >= MIN_PAIR_SAMPLES
        and result["expectancy_pips"] is not None
        and result["expectancy_pips"] > 0
        and result["profit_factor"] is not None
        and result["profit_factor"] > 1
    )
    largest_pair_share = max((result["n"] / len(values) for result in pairs.values()), default=1.0)
    pair_diversity_ok = positive_pairs >= 2 and largest_pair_share <= MAX_PAIR_OBSERVATION_SHARE

    bootstrap = _bootstrap(values)
    ruin = probability_of_ruin(
        [value - 0.5 for value in values],
        starting_capital_pips=20.0,
        simulations=RUIN_SIMULATIONS,
        horizon=len(values),
        seed=20260828,
    )
    uncertainty_supportive = (
        min(bootstrap["ordinary_lower_95_mean"], bootstrap["block_lower_95_mean"]) > 0
        and bootstrap["probability_positive_mean"] >= 0.95
        and ruin < 0.05
    )

    gates = {
        "confirmation_sample_min_100": len(values) >= MIN_CONFIRMATION_SAMPLES,
        "confirmation_expectancy_positive": bool(base["expectancy_pips"] is not None and base["expectancy_pips"] > 0),
        "confirmation_pf_gt_1": bool(base["profit_factor"] is not None and base["profit_factor"] > 1),
        "chronological_fold_stability": all_folds_positive,
        "stress_resilient_0_to_1_5_pips": stress_resilient,
        "uncertainty_supportive": uncertainty_supportive,
        "positive_pair_count_min_2_and_min_20_each": positive_pairs >= 2,
        "pair_observation_concentration_lte_80pct": largest_pair_share <= MAX_PAIR_OBSERVATION_SHARE,
    }
    passed = all(gates.values())
    return {
        "state": "PASS" if passed else "FAIL",
        "reason": "primary fresh candidate passed all predefined confirmation robustness gates" if passed else "primary fresh candidate failed one or more predefined confirmation robustness gates",
        "candidate": primary,
        "candidate_fingerprint": fingerprint,
        "candidate_selection_rule": "rank-1 discovery candidate only; confirmation results never select an alternate candidate",
        "confirmation": base,
        "confirmation_folds": folds,
        "confirmation_pair_breakdown": pairs,
        "positive_pair_count": positive_pairs,
        "largest_pair_observation_share": largest_pair_share,
        "stress": stress,
        "bootstrap": bootstrap,
        "ruin_probability_after_0_5_pip_stress": ruin,
        "gates": gates,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def run(input_dir: Path, discovery_report_path: Path, sample_stride: int, history_states: int) -> dict[str, Any]:
    report = json.loads(discovery_report_path.read_text(encoding="utf-8"))
    all_records: list[dict[str, Any]] = []
    costs = ExecutionAssumptions()
    for pair in PAIR_TO_SYMBOL:
        records, _quality = experiment.analyze_pair(
            pair,
            load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"),
            sample_stride,
            history_states,
            costs,
        )
        all_records.extend(records)
    result = evaluate_primary(report, all_records)
    result["source_discovery_candidate_count"] = report.get("candidate_count")
    result["source_discovery_record_count"] = report.get("record_count")
    result["source_discovery_status"] = report.get("status")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Confirm only the rank-1 fresh discovery candidate on the untouched confirmation segment.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--discovery-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    args = parser.parse_args()
    if args.sample_stride <= 0 or args.history_states <= 0:
        raise SystemExit("sample-stride and history-states must be positive")
    result = run(Path(args.input_dir), Path(args.discovery_report), args.sample_stride, args.history_states)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"FRESH_PRIMARY_CONFIRMATION_STATE={result['state']}")
    print(f"PROMOTION_AUTHORIZED={result['promotion_authorized']}")
    print(f"LIVE_EXECUTION_AUTHORIZED={result['live_execution_authorized']}")


if __name__ == "__main__":
    main()
