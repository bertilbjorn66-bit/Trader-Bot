from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

from research.non_live_evaluation import (
    block_bootstrap_means,
    bootstrap_means,
    max_drawdown,
    probability_of_ruin,
    profit_factor,
)

MIN_CONFIRMATION_SAMPLES = 100
FOLDS = 4
COST_STRESS_PIPS = (0.0, 0.2, 0.5, 1.0)
BOOTSTRAP_REPS = 2000
RUIN_SIMULATIONS = 5000

FROZEN_CANDIDATE: dict[str, Any] = {
    "horizon": 2,
    "agreement_min": 0.5,
    "distance_max": 1.5,
    "regime": "regime:high_volatility_range",
    "session": "new_york",
    "pairset": "all",
}

FROZEN_DISCOVERY_SNAPSHOT = {
    "n": 243,
    "expectancy_pips": 1.9234567901234763,
    "profit_factor": 1.6541637508747473,
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


FROZEN_CANDIDATE_FINGERPRINT = hashlib.sha256(_canonical_json(FROZEN_CANDIDATE).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Stats:
    n: int
    expectancy_pips: float
    profit_factor: float | None
    win_rate: float
    max_drawdown_pips: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "expectancy_pips": self.expectancy_pips,
            "profit_factor": self.profit_factor,
            "win_rate": self.win_rate,
            "max_drawdown_pips": self.max_drawdown_pips,
        }


def stats(values: Sequence[float]) -> Stats | None:
    if not values:
        return None
    wins = sum(value > 0 for value in values)
    return Stats(
        n=len(values),
        expectancy_pips=mean(values),
        profit_factor=profit_factor(values),
        win_rate=wins / len(values),
        max_drawdown_pips=max_drawdown(values),
    )


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
        and float(record["agreement"]) >= float(candidate["agreement_min"])
    )


def _ordered_records(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda record: datetime.fromisoformat(str(record["timestamp"])))


def _outcomes(records: Sequence[dict[str, Any]]) -> list[float]:
    return [float(record["outcome_pips"]) for record in _ordered_records(records)]


def _folds(values: Sequence[float], folds: int = FOLDS) -> list[dict[str, Any]]:
    if folds <= 0 or len(values) < folds:
        return []
    size = len(values) // folds
    result: list[dict[str, Any]] = []
    for fold_id in range(folds):
        start = fold_id * size
        end = len(values) if fold_id == folds - 1 else (fold_id + 1) * size
        fold_stats = stats(values[start:end])
        result.append({"fold_id": fold_id, "stats": fold_stats.as_dict() if fold_stats else None})
    return result


def _stress(values: Sequence[float]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for cost in COST_STRESS_PIPS:
        stressed = [value - cost for value in values]
        result[str(cost)] = stats(stressed).as_dict() if stressed else {}
    return result


def _bootstrap(values: Sequence[float]) -> dict[str, Any]:
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=0)
    block = block_bootstrap_means(values, block_size=min(5, len(values)), reps=BOOTSTRAP_REPS, seed=1)
    return {
        "ordinary_lower_95_mean": ordinary[24],
        "ordinary_upper_95_mean": ordinary[-25],
        "block_lower_95_mean": block[24],
        "block_upper_95_mean": block[-25],
        "probability_positive_mean": mean(value > 0 for value in ordinary),
    }


def _pair_breakdown(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    values: dict[str, list[float]] = {}
    for record in records:
        values.setdefault(str(record["pair"]), []).append(float(record["outcome_pips"]))
    return {pair: stats(pair_values).as_dict() if stats(pair_values) else None for pair, pair_values in sorted(values.items())}


def _assert_frozen_discovery(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    discovery = [record for record in records if _matches(record, FROZEN_CANDIDATE, "discovery")]
    result = stats(_outcomes(discovery))
    if result is None:
        raise ValueError("frozen candidate has no discovery observations")
    if result.n != FROZEN_DISCOVERY_SNAPSHOT["n"]:
        raise ValueError(f"frozen discovery count changed: {result.n} != {FROZEN_DISCOVERY_SNAPSHOT['n']}")
    if abs(result.expectancy_pips - FROZEN_DISCOVERY_SNAPSHOT["expectancy_pips"]) > 1e-9:
        raise ValueError("frozen discovery expectancy changed")
    if result.profit_factor is None or abs(result.profit_factor - FROZEN_DISCOVERY_SNAPSHOT["profit_factor"]) > 1e-9:
        raise ValueError("frozen discovery profit factor changed")
    return result.as_dict()


def evaluate(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "state": "INCOMPLETE",
            "reason": "no target records supplied",
            "candidate": FROZEN_CANDIDATE,
            "candidate_fingerprint": FROZEN_CANDIDATE_FINGERPRINT,
            "holdout_used_for_freeze": False,
        }

    discovery_stats = _assert_frozen_discovery(records)
    confirmation_records = [record for record in records if _matches(record, FROZEN_CANDIDATE, "confirmation")]
    confirmation_values = _outcomes(confirmation_records)

    if not confirmation_values:
        return {
            "state": "INCOMPLETE",
            "reason": "frozen candidate produced no confirmation observations",
            "candidate": FROZEN_CANDIDATE,
            "candidate_fingerprint": FROZEN_CANDIDATE_FINGERPRINT,
            "holdout_used_for_freeze": False,
            "discovery": discovery_stats,
        }

    confirmation = stats(confirmation_values)
    assert confirmation is not None
    sample_complete = confirmation.n >= MIN_CONFIRMATION_SAMPLES
    stress = _stress(confirmation_values)
    bootstrap = _bootstrap(confirmation_values)
    ruin = probability_of_ruin(
        [value - COST_STRESS_PIPS[1] for value in confirmation_values],
        starting_capital_pips=20.0,
        simulations=RUIN_SIMULATIONS,
        horizon=len(confirmation_values),
        seed=2,
    )
    folds = _folds(confirmation_values)
    all_folds_positive = bool(folds) and all(
        fold["stats"] is not None and fold["stats"]["expectancy_pips"] > 0
        for fold in folds
    )
    positive_pairs = sum(
        1
        for value in _pair_breakdown(confirmation_records).values()
        if value is not None
        and value["expectancy_pips"] > 0
        and value["profit_factor"] is not None
        and value["profit_factor"] > 1
    )
    stress_positive = all(
        value.get("expectancy_pips", 0) > 0
        and value.get("profit_factor") is not None
        and value["profit_factor"] > 1
        for value in stress.values()
    )
    uncertainty_supportive = (
        min(bootstrap["ordinary_lower_95_mean"], bootstrap["block_lower_95_mean"]) > 0
        and bootstrap["probability_positive_mean"] >= 0.95
        and ruin < 0.05
    )

    gates = {
        "confirmation_sample_min_100": sample_complete,
        "confirmation_expectancy_positive": confirmation.expectancy_pips > 0,
        "confirmation_pf_gt_1": confirmation.profit_factor is not None and confirmation.profit_factor > 1,
        "chronological_fold_stability": all_folds_positive,
        "stress_resilient_0_to_1_pips": stress_positive,
        "uncertainty_supportive": uncertainty_supportive,
        "positive_pair_count_min_2": positive_pairs >= 2,
    }

    if not sample_complete:
        state = "INCOMPLETE"
        reason = "confirmation sample is below the predefined minimum"
    elif all(gates.values()):
        state = "PASS"
        reason = "frozen candidate passed all predefined confirmation robustness gates"
    else:
        state = "FAIL"
        reason = "frozen candidate failed one or more predefined confirmation robustness gates"

    return {
        "state": state,
        "reason": reason,
        "candidate": FROZEN_CANDIDATE,
        "candidate_fingerprint": FROZEN_CANDIDATE_FINGERPRINT,
        "holdout_used_for_freeze": False,
        "freeze_rule": "candidate specification and discovery snapshot are immutable; confirmation outcomes are evaluated only after freeze",
        "discovery": discovery_stats,
        "confirmation": confirmation.as_dict(),
        "confirmation_pair_breakdown": _pair_breakdown(confirmation_records),
        "confirmation_folds": folds,
        "positive_pair_count": positive_pairs,
        "stress": stress,
        "bootstrap": bootstrap,
        "ruin_probability": ruin,
        "gates": gates,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate one immutable discovery-era candidate on untouched confirmation data.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records = payload["target_records"]
    methodology = payload.get("methodology", {})
    if not str(methodology.get("split", "")).startswith("chronological 60/40"):
        raise ValueError("frozen candidate experiment requires the preserved chronological 60/40 split")
    if int(methodology.get("holdout_min_samples", 0)) != MIN_CONFIRMATION_SAMPLES:
        raise ValueError("unexpected holdout minimum in source experiment")

    result = evaluate(records)
    result["source_experiment_status"] = payload.get("status")
    result["source_record_count"] = payload.get("record_count")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"FROZEN_CANDIDATE_FINGERPRINT={FROZEN_CANDIDATE_FINGERPRINT}")
    print(f"FROZEN_CANDIDATE_STATE={result['state']}")
    print(f"PROMOTION_AUTHORIZED={result.get('promotion_authorized', False)}")
    print(f"LIVE_EXECUTION_AUTHORIZED={result.get('live_execution_authorized', False)}")


if __name__ == "__main__":
    main()
