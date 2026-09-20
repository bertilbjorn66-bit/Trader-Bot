from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from math import inf
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from research.bidirectional_analogue_discovery import (
    CONTRACT_VERSION,
    rebuild_target_records,
)
from research.non_live_evaluation import (
    block_bootstrap_means,
    bootstrap_means,
    max_drawdown,
    probability_of_ruin,
    profit_factor,
)

CONFIRMATION_CONTRACT_VERSION = "v1-bidirectional-analogue-confirmation"
MIN_CONFIRMATION_SAMPLES = 500
MIN_PAIR_SAMPLES = 20
MIN_POSITIVE_PAIRS = 3
MAX_PAIR_OBSERVATION_SHARE = 0.80
FOLDS = 4
STRESS_COSTS_PIPS = (0.0, 0.2, 0.5, 1.0, 1.5)
BOOTSTRAP_REPS = 2000
RUIN_SIMULATIONS = 5000


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def candidate_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "direction": str(candidate["direction"]),
        "direction_policy": str(candidate["direction_policy"]),
        "horizon": int(candidate["horizon"]),
        "k": int(candidate["k"]),
    }


def candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(candidate_identity(candidate)).encode("utf-8")).hexdigest()


def _matches(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    return (
        str(record["global_split"]) == "confirmation"
        and int(record["horizon"]) == int(candidate["horizon"])
        and int(record["k"]) == int(candidate["k"])
        and str(record["direction"]) in {"long", "short"}
    )


def _ordered_values(records: Sequence[Mapping[str, Any]]) -> list[float]:
    ordered = sorted(records, key=lambda record: datetime.fromisoformat(str(record["timestamp"])))
    return [float(record["outcome_pips"]) for record in ordered]


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "expectancy_pips": None,
            "profit_factor": None,
            "win_rate": None,
            "max_drawdown_pips": None,
            "net_profit_pips": 0.0,
        }
    return {
        "n": len(values),
        "expectancy_pips": mean(values),
        "profit_factor": profit_factor(values),
        "win_rate": sum(value > 0 for value in values) / len(values),
        "max_drawdown_pips": max_drawdown(values),
        "net_profit_pips": sum(values),
    }


def _folds(values: Sequence[float]) -> list[dict[str, Any]]:
    if len(values) < FOLDS:
        return []
    size = len(values) // FOLDS
    result: list[dict[str, Any]] = []
    for fold_id in range(FOLDS):
        start = fold_id * size
        end = len(values) if fold_id == FOLDS - 1 else (fold_id + 1) * size
        result.append({"fold_id": fold_id, "stats": _stats(values[start:end])})
    return result


def _pair_breakdown(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for record in records:
        grouped.setdefault(str(record["pair"]), []).append(float(record["outcome_pips"]))
    return {pair: _stats(values) for pair, values in sorted(grouped.items())}


def _pair_diversity(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pairs = _pair_breakdown(records)
    eligible = {
        pair: stats
        for pair, stats in pairs.items()
        if int(stats["n"]) >= MIN_PAIR_SAMPLES
    }
    positive = {
        pair: stats
        for pair, stats in eligible.items()
        if stats["expectancy_pips"] is not None
        and float(stats["expectancy_pips"]) > 0.0
        and (stats["profit_factor"] is None or float(stats["profit_factor"]) > 1.0)
    }
    largest_share = max(
        (int(stats["n"]) / len(records) for stats in pairs.values()),
        default=1.0,
    )
    return {
        "pair_breakdown": pairs,
        "eligible_pair_count": len(eligible),
        "positive_pair_count": len(positive),
        "largest_pair_observation_share": largest_share,
        "passes": (
            len(positive) >= MIN_POSITIVE_PAIRS
            and largest_share <= MAX_PAIR_OBSERVATION_SHARE
        ),
    }


def _bootstrap(values: Sequence[float], seed: int) -> dict[str, float]:
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=seed)
    block = block_bootstrap_means(
        values,
        block_size=min(5, len(values)),
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


def _direction_breakdown(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = {"long": [], "short": []}
    for record in records:
        grouped[str(record["direction"])].append(float(record["outcome_pips"]))
    return {direction: _stats(values) for direction, values in grouped.items()}


def evaluate_confirmation(
    discovery_report: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if discovery_report.get("status") != "BIDIRECTIONAL_ANALOGUE_DISCOVERY_COMPLETED":
        raise ValueError("source discovery report is not a completed bidirectional discovery")
    policy = discovery_report.get("selection_policy")
    if not isinstance(policy, Mapping):
        raise ValueError("source discovery report has no selection policy")
    if policy.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("source discovery report uses an unsupported bidirectional contract")
    if policy.get("confirmation_used_for_selection") is not False:
        raise ValueError("discovery report does not prove confirmation-free selection")
    if policy.get("prior_frozen_confirmation_artifact_read") is not False:
        raise ValueError("discovery report references prior frozen confirmation evidence")

    candidates = discovery_report.get("top_candidates")
    if not isinstance(candidates, list) or not candidates:
        return {
            "state": "INCOMPLETE",
            "reason": "bidirectional discovery produced no candidate",
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    candidate = dict(candidates[0])
    required = {"direction", "direction_policy", "horizon", "k", "candidate_fingerprint"}
    if not required.issubset(candidate):
        raise ValueError("rank-1 bidirectional candidate is missing frozen identity fields")
    frozen_identity = candidate_identity(candidate)
    if frozen_identity["direction"] != "bidirectional":
        raise ValueError("rank-1 candidate is not bidirectional")
    if frozen_identity["direction_policy"] != "pre_target_analogue_mean_argmax":
        raise ValueError("rank-1 candidate uses an unsupported direction policy")
    frozen_fingerprint = candidate_fingerprint(candidate)
    if candidate["candidate_fingerprint"] != frozen_fingerprint:
        raise ValueError("rank-1 bidirectional candidate fingerprint is internally inconsistent")

    confirmation = [record for record in records if _matches(record, candidate)]
    values = _ordered_values(confirmation)
    base = _stats(values)
    if len(values) < MIN_CONFIRMATION_SAMPLES:
        return {
            "state": "INCOMPLETE",
            "reason": "bidirectional confirmation sample is below the predefined minimum",
            "candidate": candidate,
            "candidate_identity": frozen_identity,
            "candidate_fingerprint": frozen_fingerprint,
            "confirmation": base,
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    folds = _folds(values)
    all_folds_positive = bool(folds) and all(
        fold["stats"]["expectancy_pips"] is not None
        and float(fold["stats"]["expectancy_pips"]) > 0.0
        for fold in folds
    )
    stress = {
        str(cost): _stats([value - cost for value in values])
        for cost in STRESS_COSTS_PIPS
    }
    stress_resilient = all(
        stats["expectancy_pips"] is not None
        and float(stats["expectancy_pips"]) > 0.0
        and (
            stats["profit_factor"] is not None
            and float(stats["profit_factor"]) > 1.0
        )
        for stats in stress.values()
    )

    diversity = _pair_diversity(confirmation)
    bootstrap_seed = int(frozen_fingerprint[:8], 16)
    bootstrap = _bootstrap(values, bootstrap_seed)
    ruin = probability_of_ruin(
        [value - 0.5 for value in values],
        starting_capital_pips=20.0,
        simulations=RUIN_SIMULATIONS,
        horizon=len(values),
        seed=bootstrap_seed + 1,
    )
    uncertainty_supportive = (
        bootstrap["ordinary_lower_95_mean"] > 0.0
        and bootstrap["block_lower_95_mean"] > 0.0
        and bootstrap["ordinary_probability_positive_mean"] >= 0.95
        and ruin < 0.05
    )

    gates = {
        "confirmation_sample_min_500": len(values) >= MIN_CONFIRMATION_SAMPLES,
        "confirmation_expectancy_positive": bool(
            base["expectancy_pips"] is not None
            and float(base["expectancy_pips"]) > 0.0
        ),
        "confirmation_pf_gt_1": bool(
            base["profit_factor"] is not None
            and float(base["profit_factor"]) > 1.0
        ),
        "chronological_fold_stability": all_folds_positive,
        "stress_resilient_0_to_1_5_pips": stress_resilient,
        "uncertainty_supportive": uncertainty_supportive,
        "positive_pair_count_min_3_and_min_20_each": diversity["positive_pair_count"] >= MIN_POSITIVE_PAIRS,
        "pair_observation_concentration_lte_80pct": diversity["largest_pair_observation_share"] <= MAX_PAIR_OBSERVATION_SHARE,
        "pair_diversity": bool(diversity["passes"]),
    }
    passed = all(gates.values())
    return {
        "state": "PASS" if passed else "FAIL",
        "reason": (
            "bidirectional candidate passed all predefined confirmation robustness gates"
            if passed
            else "bidirectional candidate failed one or more predefined confirmation robustness gates"
        ),
        "candidate": candidate,
        "candidate_identity": frozen_identity,
        "candidate_fingerprint": frozen_fingerprint,
        "candidate_selection_rule": "rank-1 bidirectional discovery candidate only; confirmation never selects an alternate candidate",
        "confirmation": base,
        "confirmation_folds": folds,
        "confirmation_pair_breakdown": diversity["pair_breakdown"],
        "positive_pair_count": diversity["positive_pair_count"],
        "largest_pair_observation_share": diversity["largest_pair_observation_share"],
        "direction_breakdown": _direction_breakdown(confirmation),
        "stress": stress,
        "bootstrap": bootstrap,
        "ruin_probability_after_0_5_pip_stress": ruin,
        "gates": gates,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def run(
    input_dir: Path,
    discovery_report_path: Path,
    sample_stride: int,
    history_states: int,
    parallel_workers: int = 4,
) -> dict[str, Any]:
    discovery_report = json.loads(
        discovery_report_path.read_text(encoding="utf-8")
    )
    binding = discovery_report.get("orchestration_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("discovery report has no immutable orchestration binding")
    for key in ("discovery_head_sha", "discovery_run_id", "source_run_id", "sample_stride", "history_states"):
        if key not in binding:
            raise ValueError(f"discovery binding missing {key}")
    if int(binding["sample_stride"]) != sample_stride:
        raise ValueError("confirmation sample_stride does not match discovery binding")
    if int(binding["history_states"]) != history_states:
        raise ValueError("confirmation history_states does not match discovery binding")

    records, source_manifest, quality, cutoff = rebuild_target_records(
        input_dir,
        sample_stride,
        history_states,
        parallel_workers,
    )
    if cutoff != discovery_report.get("global_split_cutoff"):
        raise ValueError("rebuilt global split cutoff does not match discovery evidence")
    discovery_manifest = discovery_report.get("source_manifest")
    if discovery_manifest != source_manifest:
        raise ValueError("rebuilt source SHA-256 manifest does not match discovery evidence")

    result = evaluate_confirmation(discovery_report, records)
    result.update(
        {
            "confirmation_contract_version": CONFIRMATION_CONTRACT_VERSION,
            "global_split_cutoff": cutoff,
            "source_manifest": source_manifest,
            "data_quality": quality,
            "source_discovery_candidate_count": discovery_report.get("candidate_count"),
            "source_discovery_record_count": discovery_report.get("record_count"),
            "source_discovery_status": discovery_report.get("status"),
            "orchestration_binding": {
                "discovery_run_id": int(binding["discovery_run_id"]),
                "discovery_head_sha": str(binding["discovery_head_sha"]),
                "source_run_id": int(binding["source_run_id"]),
                "sample_stride": sample_stride,
                "history_states": history_states,
            },
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Confirm only the frozen rank-1 bidirectional analogue candidate."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--discovery-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--parallel-workers", type=int, default=4)
    args = parser.parse_args()
    result = run(
        Path(args.input_dir),
        Path(args.discovery_report),
        args.sample_stride,
        args.history_states,
        args.parallel_workers,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"BIDIRECTIONAL_CONFIRMATION_STATE={result['state']}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
