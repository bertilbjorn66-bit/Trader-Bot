from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from research.intelligence_controls import ExecutionCostModel
from research.multiple_testing import holm_bonferroni
from research.non_live_evaluation import (
    block_bootstrap_means,
    bootstrap_means,
    max_drawdown,
    profit_factor,
)

EXPECTED_BAR_INTERVAL = timedelta(minutes=10)
FOLDS = 12
MIN_RUN_TRADES = 500
MIN_SERIES_TRADES = 20
MIN_SERIES = 3
MIN_POSITIVE_SERIES = 3
BOOTSTRAP_REPS = 2000
BOOTSTRAP_LOWER_INDEX = 49
BOOTSTRAP_UPPER_INDEX = -50
BOOTSTRAP_BLOCK_SIZE = 5
HAC_LAG = 5
HOLM_ALPHA = 0.05
MIN_RECOVERY_RATIO = 1.0
PARAMETER_PERTURBATIONS = (-0.10, -0.05, 0.05, 0.10)

EXECUTION_MODELS: tuple[tuple[str, ExecutionCostModel], ...] = (
    ("nominal_plus", ExecutionCostModel(spread_pips=0.0, slippage_pips=0.20, latency_pips=0.20)),
    ("realistic_plus", ExecutionCostModel(spread_pips=0.0, slippage_pips=0.50, latency_pips=0.30)),
    ("adverse_plus", ExecutionCostModel(spread_pips=0.0, slippage_pips=1.00, latency_pips=0.50)),
)


@dataclass(frozen=True)
class PurgedFold:
    fold_id: int
    start: datetime
    end: datetime | None
    records: tuple[dict[str, Any], ...]
    purged_at_start: int
    purged_at_end: int


def _timestamp(record: Mapping[str, Any]) -> datetime:
    value = datetime.fromisoformat(str(record["timestamp"]))
    if value.tzinfo is None:
        raise ValueError("record timestamps must be timezone-aware")
    return value


def _candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    payload = json.dumps(_candidate_identity(candidate), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _candidate_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: candidate[key]
        for key in ("horizon", "agreement_min", "distance_max", "regime", "session", "pairset")
    }


def _matches(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    return (
        int(record["horizon"]) == int(candidate["horizon"])
        and str(record["regime"]) == str(candidate["regime"])
        and str(record["session"]) == str(candidate["session"])
        and (candidate["pairset"] == "all" or str(record["pair"]).endswith("/JPY"))
        and (
            candidate["distance_max"] is None
            or float(record["median_distance"]) <= float(candidate["distance_max"])
        )
        and float(record["agreement"]) >= float(candidate["agreement_min"])
        and str(record["split"]) == "confirmation"
    )


def build_purged_folds(
    records: Sequence[Mapping[str, Any]],
    horizon: int,
    folds: int = FOLDS,
    timeline_records: Sequence[Mapping[str, Any]] | None = None,
) -> list[PurgedFold]:
    if folds <= 1:
        raise ValueError("folds must be greater than one")
    ordered = sorted((dict(record) for record in records), key=_timestamp)
    timeline = list(timeline_records) if timeline_records is not None else ordered
    timeline_timestamps = sorted({_timestamp(record) for record in timeline})
    if len(timeline_timestamps) < folds:
        return []

    boundaries = [
        timeline_timestamps[(len(timeline_timestamps) * index) // folds]
        for index in range(folds)
    ]
    boundaries.append(timeline_timestamps[-1] + EXPECTED_BAR_INTERVAL)
    purge = horizon * EXPECTED_BAR_INTERVAL
    result: list[PurgedFold] = []

    for fold_id in range(folds):
        start = boundaries[fold_id]
        end = None if fold_id == folds - 1 else boundaries[fold_id + 1]
        candidate_records = [
            record
            for record in ordered
            if _timestamp(record) >= start + purge
            and (end is None or _timestamp(record) < end)
        ]
        purged_start = sum(
            1
            for record in ordered
            if start <= _timestamp(record) < start + purge
        )
        purged_end = 0
        if end is not None:
            safe: list[dict[str, Any]] = []
            for record in candidate_records:
                finish = _timestamp(record) + int(record["horizon"]) * EXPECTED_BAR_INTERVAL
                if finish < end:
                    safe.append(record)
                else:
                    purged_end += 1
            candidate_records = safe
        result.append(PurgedFold(fold_id, start, end, tuple(candidate_records), purged_start, purged_end))

    return result


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "expectancy_pips": None,
            "profit_factor": None,
            "net_profit_pips": 0.0,
            "max_drawdown_pips": None,
            "recovery_ratio": None,
        }
    expectancy = mean(values)
    dd = max_drawdown(values)
    net_profit = sum(values)
    recovery = math.inf if dd == 0.0 and net_profit > 0.0 else (net_profit / dd if dd > 0.0 else 0.0)
    return {
        "n": len(values),
        "expectancy_pips": expectancy,
        "profit_factor": profit_factor(values),
        "net_profit_pips": net_profit,
        "max_drawdown_pips": dd,
        "recovery_ratio": recovery,
    }


def _pair_stats(records: Sequence[Mapping[str, Any]], values: Sequence[float]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for record, value in zip(records, values, strict=True):
        grouped.setdefault(str(record["pair"]), []).append(value)
    return {pair: _stats(pair_values) for pair, pair_values in sorted(grouped.items())}


def _bootstrap(values: Sequence[float], seed: int) -> dict[str, float]:
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=seed)
    block = block_bootstrap_means(
        values,
        block_size=min(BOOTSTRAP_BLOCK_SIZE, len(values)),
        reps=BOOTSTRAP_REPS,
        seed=seed + 1,
    )
    return {
        "ordinary_lower_95_mean": ordinary[BOOTSTRAP_LOWER_INDEX],
        "ordinary_upper_95_mean": ordinary[BOOTSTRAP_UPPER_INDEX],
        "block_lower_95_mean": block[BOOTSTRAP_LOWER_INDEX],
        "block_upper_95_mean": block[BOOTSTRAP_UPPER_INDEX],
        "ordinary_probability_positive_mean": mean(value > 0.0 for value in ordinary),
    }


def hac_mean_pvalue(values: Sequence[float], max_lag: int = HAC_LAG) -> float:
    if len(values) < 2:
        raise ValueError("HAC p-value requires at least two observations")
    if max_lag < 0 or max_lag >= len(values):
        raise ValueError("invalid HAC lag")
    centre = mean(values)
    centred = [value - centre for value in values]
    gamma_0 = mean(value * value for value in centred)
    variance = gamma_0
    for lag in range(1, max_lag + 1):
        gamma = mean(
            centred[index] * centred[index - lag]
            for index in range(lag, len(values))
        )
        weight = 1.0 - lag / (max_lag + 1.0)
        variance += 2.0 * weight * gamma
    variance = max(variance, 0.0)
    standard_error = math.sqrt(variance / len(values))
    if standard_error == 0.0:
        return 0.0 if centre > 0.0 else 1.0
    z = centre / standard_error
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _execution_values(records: Sequence[Mapping[str, Any]], model: ExecutionCostModel) -> list[float]:
    net_cost = model.total_cost_pips()
    return [float(record["outcome_pips"]) - net_cost for record in records]


def _run_gates(
    records: Sequence[Mapping[str, Any]],
    values: Sequence[float],
    raw_pvalue: float,
    adjusted_pvalue: float,
) -> dict[str, bool]:
    base = _stats(values)
    pairs = _pair_stats(records, values)
    eligible_series = {
        pair: result
        for pair, result in pairs.items()
        if result["n"] >= MIN_SERIES_TRADES
    }
    positive_series = {
        pair: result
        for pair, result in eligible_series.items()
        if result["expectancy_pips"] > 0.0
        and result["profit_factor"] is not None
        and result["profit_factor"] > 1.0
    }
    bootstrap = _bootstrap(values, 2026091901 + len(values))
    return {
        "test_trades_min_500": len(values) >= MIN_RUN_TRADES,
        "series_min_3": len(eligible_series) >= MIN_SERIES,
        "positive_series_min_3": len(positive_series) >= MIN_POSITIVE_SERIES,
        "expectancy_positive": bool(base["expectancy_pips"] is not None and base["expectancy_pips"] > 0.0),
        "profit_factor_gt_1": bool(base["profit_factor"] is not None and base["profit_factor"] > 1.0),
        "drawdown_recovery_ratio_ge_1": bool(
            base["recovery_ratio"] is not None and base["recovery_ratio"] >= MIN_RECOVERY_RATIO
        ),
        "ordinary_bootstrap_lower_positive": bootstrap["ordinary_lower_95_mean"] > 0.0,
        "block_bootstrap_lower_positive": bootstrap["block_lower_95_mean"] > 0.0,
        "bootstrap_probability_positive_ge_95pct": bootstrap["ordinary_probability_positive_mean"] >= 0.95,
        "holm_adjusted_p_le_005": adjusted_pvalue <= HOLM_ALPHA,
    }


def _parameter_variants(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for field in ("agreement_min", "distance_max"):
        base = candidate[field]
        if base is None:
            continue
        for delta in PARAMETER_PERTURBATIONS:
            value = float(base) * (1.0 + delta)
            if field == "agreement_min":
                value = min(max(value, 0.01), 0.99)
            else:
                value = max(value, 0.01)
            variant = dict(candidate)
            variant[field] = value
            variants.append(variant)
    return variants


def evaluate_parameter_stability(
    candidate: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    folds: Sequence[PurgedFold],
    timeline_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    variants = _parameter_variants(candidate)
    if not variants:
        return {
            "variant_count": 0,
            "all_variants_pass": False,
            "reason": "candidate has no numeric threshold available for perturbation audit",
            "variants": [],
        }
    variant_results: list[dict[str, Any]] = []
    for index, variant in enumerate(variants):
        matched = [record for record in records if _matches(record, variant)]
        variant_folds = build_purged_folds(
            matched,
            int(variant["horizon"]),
            len(folds),
            timeline_records=timeline_records,
        )
        fold_expectancies: list[float] = []
        fold_pfs: list[float | None] = []
        for fold in variant_folds:
            values = [float(record["outcome_pips"]) for record in fold.records]
            stats = _stats(values)
            fold_expectancies.append(float(stats["expectancy_pips"] or 0.0))
            fold_pfs.append(stats["profit_factor"])
        aggregate = _stats([float(record["outcome_pips"]) for record in matched])
        passed = (
            len(variant_folds) == len(folds)
            and bool(fold_expectancies)
            and all(value > 0.0 for value in fold_expectancies)
            and all(pf is not None and pf > 1.0 for pf in fold_pfs)
            and aggregate["n"] >= MIN_RUN_TRADES
            and aggregate["expectancy_pips"] > 0.0
            and aggregate["profit_factor"] is not None
            and aggregate["profit_factor"] > 1.0
        )
        variant_results.append({
            "variant_id": index + 1,
            "candidate": _candidate_identity(variant),
            "n": aggregate["n"],
            "expectancy_pips": aggregate["expectancy_pips"],
            "profit_factor": aggregate["profit_factor"],
            "fold_expectancies": fold_expectancies,
            "fold_profit_factors": fold_pfs,
            "passed": passed,
        })
    return {
        "variant_count": len(variant_results),
        "all_variants_pass": all(item["passed"] for item in variant_results),
        "variants": variant_results,
    }


def certify(
    discovery_report: Mapping[str, Any],
    confirmation_report: Mapping[str, Any],
    all_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if discovery_report.get("status") != "FRESH_DISCOVERY_COMPLETED":
        raise ValueError("discovery report is not a completed fresh discovery")
    if discovery_report.get("selection_policy", {}).get("confirmation_used_for_selection") is not False:
        raise ValueError("discovery report does not prove confirmation-free candidate selection")
    if discovery_report.get("selection_policy", {}).get("prior_frozen_confirmation_artifact_read") is not False:
        raise ValueError("discovery report references prior frozen confirmation evidence")
    if confirmation_report.get("state") != "PASS":
        return {
            "state": "INCOMPLETE",
            "reason": "fresh primary confirmation did not pass, so certification cannot proceed",
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    candidates = discovery_report.get("top_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("discovery report has no candidate")
    candidate = dict(candidates[0])
    if "confirmation" in candidate:
        raise ValueError("discovery candidate unexpectedly contains confirmation data")
    candidate["rank"] = 1
    if confirmation_report.get("candidate", {}).get("rank") != 1:
        raise ValueError("confirmation report is not for rank-1 discovery candidate")

    selected = _candidate_identity(candidate)
    confirmed = _candidate_identity(confirmation_report["candidate"])
    if selected != confirmed:
        raise ValueError("confirmation candidate does not match discovery rank-1 candidate")
    expected_fingerprint = _candidate_fingerprint(candidate)
    if confirmation_report.get("candidate_fingerprint") != expected_fingerprint:
        raise ValueError("confirmation candidate fingerprint does not match the frozen rank-1 candidate")

    candidate_records = [record for record in all_records if _matches(record, candidate)]
    folds = build_purged_folds(
        candidate_records,
        int(candidate["horizon"]),
        FOLDS,
        timeline_records=all_records,
    )
    if len(folds) != FOLDS:
        return {
            "state": "INCOMPLETE",
            "reason": "confirmation evidence cannot form the required twelve purged chronological runs",
            "candidate": candidate,
            "fold_count": len(folds),
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    run_specs = [(fold, name, model) for fold in folds for name, model in EXECUTION_MODELS]
    raw_pvalues: list[float] = []
    run_payloads: list[dict[str, Any]] = []

    for fold, model_name, model in run_specs:
        records = list(fold.records)
        values = _execution_values(records, model)
        raw_pvalue = hac_mean_pvalue(values)
        raw_pvalues.append(raw_pvalue)
        run_payloads.append({
            "fold_id": fold.fold_id,
            "execution_model": model_name,
            "execution_cost_pips": model.total_cost_pips(),
            "records": records,
            "values": values,
            "raw_pvalue": raw_pvalue,
        })

    adjusted = holm_bonferroni(raw_pvalues)
    certification_runs: list[dict[str, Any]] = []
    for payload, adjusted_pvalue in zip(run_payloads, adjusted, strict=True):
        values = payload["values"]
        records = payload["records"]
        gates = _run_gates(records, values, payload["raw_pvalue"], adjusted_pvalue)
        certification_runs.append({
            "fold_id": payload["fold_id"],
            "execution_model": payload["execution_model"],
            "execution_cost_pips": payload["execution_cost_pips"],
            "statistics": _stats(values),
            "series_breakdown": _pair_stats(records, values),
            "raw_hac_one_sided_pvalue": payload["raw_pvalue"],
            "holm_adjusted_pvalue": adjusted_pvalue,
            "gates": gates,
            "qualifies": all(gates.values()),
        })

    stability = evaluate_parameter_stability(candidate, candidate_records, folds, all_records)
    qualifying_runs = sum(run["qualifies"] for run in certification_runs)
    all_runs_qualify = qualifying_runs == len(certification_runs) == 12
    aggregate_values = [
        value
        for fold in folds
        for value in _execution_values(list(fold.records), EXECUTION_MODELS[1][1])
    ]
    aggregate_stats = _stats(aggregate_values)

    gates = {
        "exactly_12_qualifying_runs": all_runs_qualify,
        "three_execution_models": len(EXECUTION_MODELS) >= 3,
        "four_purged_walk_forward_folds": len(folds) == 4,
        "min_500_trades_per_run": all(run["statistics"]["n"] >= MIN_RUN_TRADES for run in certification_runs),
        "min_3_series_per_run": all(
            sum(result["n"] >= MIN_SERIES_TRADES for result in run["series_breakdown"].values()) >= MIN_SERIES
            for run in certification_runs
        ),
        "min_3_positive_series_per_run": all(
            sum(
                result["n"] >= MIN_SERIES_TRADES
                and result["expectancy_pips"] > 0.0
                and result["profit_factor"] is not None
                and result["profit_factor"] > 1.0
                for result in run["series_breakdown"].values()
            ) >= MIN_POSITIVE_SERIES
            for run in certification_runs
        ),
        "purged_walk_forward_stability": all(
            run["statistics"]["expectancy_pips"] is not None and run["statistics"]["expectancy_pips"] > 0.0
            for run in certification_runs
        ),
        "parameter_stability": bool(stability["all_variants_pass"]),
        "drawdown_recovery": all(
            run["statistics"]["recovery_ratio"] is not None
            and run["statistics"]["recovery_ratio"] >= MIN_RECOVERY_RATIO
            for run in certification_runs
        ),
        "bootstrap_robustness": all(
            run["gates"]["ordinary_bootstrap_lower_positive"]
            and run["gates"]["block_bootstrap_lower_positive"]
            and run["gates"]["bootstrap_probability_positive_ge_95pct"]
            for run in certification_runs
        ),
        "multiple_testing_holm": all(run["gates"]["holm_adjusted_p_le_005"] for run in certification_runs),
        "execution_cost_robustness": all(
            run["statistics"]["expectancy_pips"] is not None and run["statistics"]["expectancy_pips"] > 0.0
            for run in certification_runs
        ),
        "aggregate_realistic_model_positive": aggregate_stats["expectancy_pips"] > 0.0,
        "aggregate_realistic_model_pf_gt1": aggregate_stats["profit_factor"] is not None and aggregate_stats["profit_factor"] > 1.0,
    }

    passed = all(gates.values())
    return {
        "state": "PASS" if passed else "FAIL",
        "reason": "all predefined purged certification requirements passed" if passed else "one or more predefined purged certification requirements failed",
        "candidate": candidate,
        "candidate_fingerprint": confirmation_report.get("candidate_fingerprint"),
        "candidate_selection_rule": "rank-1 fresh discovery candidate is frozen; certification never selects an alternate candidate",
        "fold_contract": {
            "fold_count": FOLDS,
            "purge_bars": int(candidate["horizon"]),
            "purge_interval": str(int(candidate["horizon"]) * 10) + " minutes",
            "boundary_rule": "test observations must begin after the fold-start purge and their complete target outcome must finish strictly before the next fold boundary",
        },
        "execution_models": {
            name: {
                "spread_pips": model.spread_pips,
                "slippage_pips": model.slippage_pips,
                "latency_pips": model.latency_pips,
                "financing_pips": model.financing_pips,
                "total_cost_pips": model.total_cost_pips(),
            }
            for name, model in EXECUTION_MODELS
        },
        "certification_runs": certification_runs,
        "qualifying_run_count": qualifying_runs,
        "parameter_stability": stability,
        "aggregate_realistic_model": aggregate_stats,
        "gates": gates,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strict purged walk-forward certification on the frozen rank-1 candidate.")
    parser.add_argument("--discovery-report", required=True)
    parser.add_argument("--confirmation-report", required=True)
    parser.add_argument("--records", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    discovery = json.loads(Path(args.discovery_report).read_text(encoding="utf-8"))
    confirmation = json.loads(Path(args.confirmation_report).read_text(encoding="utf-8"))
    records = json.loads(Path(args.records).read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("records input must be a JSON array")
    result = certify(discovery, confirmation, records)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"PURGED_CERTIFICATION_STATE={result['state']}")
    print(f"QUALIFYING_RUN_COUNT={result.get('qualifying_run_count', 0)}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
