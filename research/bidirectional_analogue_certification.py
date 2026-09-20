from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from research.bidirectional_analogue_confirmation import (
    CONFIRMATION_CONTRACT_VERSION,
    candidate_fingerprint,
    candidate_identity,
)
from research.bidirectional_analogue_discovery import (
    CONTRACT_VERSION,
    HORIZONS,
    K_VALUES,
    rebuild_target_records,
)
from research.intelligence_controls import ExecutionCostModel
from research.multiple_testing import holm_bonferroni
from research.non_live_evaluation import (
    block_bootstrap_means,
    bootstrap_means,
    max_drawdown,
    profit_factor,
)
from research.statistics import hac_mean_pvalue

FOLDS = 12
EXPECTED_BAR_INTERVAL = timedelta(minutes=10)
MIN_RUN_TRADES = 500
MIN_SERIES_TRADES = 20
MIN_SERIES = 3
MIN_POSITIVE_SERIES = 3
MAX_PAIR_OBSERVATION_SHARE = 0.80
BOOTSTRAP_REPS = 2000
BOOTSTRAP_LOWER_INDEX = 49
BOOTSTRAP_UPPER_INDEX = -50
BOOTSTRAP_BLOCK_SIZE = 5
HOLM_ALPHA = 0.05
MIN_RECOVERY_RATIO = 1.0
EXECUTION_MODELS: tuple[tuple[str, ExecutionCostModel], ...] = (
    (
        "nominal_plus",
        ExecutionCostModel(spread_pips=0.0, slippage_pips=0.20, latency_pips=0.20),
    ),
    (
        "realistic_plus",
        ExecutionCostModel(spread_pips=0.0, slippage_pips=0.50, latency_pips=0.30),
    ),
    (
        "adverse_plus",
        ExecutionCostModel(spread_pips=0.0, slippage_pips=1.00, latency_pips=0.50),
    ),
)


def _timestamp(record: Mapping[str, Any]) -> datetime:
    value = datetime.fromisoformat(str(record["timestamp"]))
    if value.tzinfo is None:
        raise ValueError("record timestamp must be timezone-aware")
    return value


def _candidate_matches(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    return (
        str(record["global_split"]) == "confirmation"
        and int(record["horizon"]) == int(candidate["horizon"])
        and int(record["k"]) == int(candidate["k"])
        and str(record["direction"]) in {"long", "short"}
    )


def _canonical_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    identity = candidate_identity(candidate)
    if identity["direction"] != "bidirectional":
        raise ValueError("candidate is not bidirectional")
    if identity["direction_policy"] != "pre_target_analogue_mean_argmax":
        raise ValueError("candidate uses an unsupported direction policy")
    if int(identity["horizon"]) not in HORIZONS:
        raise ValueError("candidate horizon is outside the frozen family")
    if int(identity["k"]) not in K_VALUES:
        raise ValueError("candidate k is outside the frozen family")
    return identity


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
    drawdown = max_drawdown(values)
    net_profit = sum(values)
    recovery = (
        math.inf
        if drawdown == 0.0 and net_profit > 0.0
        else net_profit / drawdown
        if drawdown > 0.0
        else 0.0
    )
    return {
        "n": len(values),
        "expectancy_pips": expectancy,
        "profit_factor": profit_factor(values),
        "net_profit_pips": net_profit,
        "max_drawdown_pips": drawdown,
        "recovery_ratio": recovery,
    }


def _pair_stats(
    records: Sequence[Mapping[str, Any]],
    values: Sequence[float],
) -> dict[str, dict[str, Any]]:
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


class PurgedFold:
    def __init__(
        self,
        fold_id: int,
        start: datetime,
        end: datetime | None,
        records: tuple[dict[str, Any], ...],
        purged_at_start: int,
        purged_at_end: int,
    ) -> None:
        self.fold_id = fold_id
        self.start = start
        self.end = end
        self.records = records
        self.purged_at_start = purged_at_start
        self.purged_at_end = purged_at_end


def build_purged_folds(
    records: Sequence[Mapping[str, Any]],
    horizon: int,
    folds: int = FOLDS,
    timeline_records: Sequence[Mapping[str, Any]] | None = None,
) -> list[PurgedFold]:
    if folds <= 1:
        raise ValueError("fold count must be greater than one")
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
                finish = (
                    _timestamp(record)
                    + int(record["horizon"]) * EXPECTED_BAR_INTERVAL
                )
                if finish < end:
                    safe.append(record)
                else:
                    purged_end += 1
            candidate_records = safe
        result.append(
            PurgedFold(
                fold_id,
                start,
                end,
                tuple(candidate_records),
                purged_start,
                purged_end,
            )
        )
    return result


def _execution_values(
    records: Sequence[Mapping[str, Any]],
    model: ExecutionCostModel,
) -> list[float]:
    cost = model.total_cost_pips()
    return [float(record["outcome_pips"]) - cost for record in records]


def _run_gates(
    records: Sequence[Mapping[str, Any]],
    values: Sequence[float],
    adjusted_pvalue: float,
) -> dict[str, bool]:
    base = _stats(values)
    pairs = _pair_stats(records, values)
    eligible = {
        pair: stats
        for pair, stats in pairs.items()
        if int(stats["n"]) >= MIN_SERIES_TRADES
    }
    positive = {
        pair: stats
        for pair, stats in eligible.items()
        if stats["expectancy_pips"] is not None
        and float(stats["expectancy_pips"]) > 0.0
        and stats["profit_factor"] is not None
        and float(stats["profit_factor"]) > 1.0
    }
    concentration = max(
        (int(stats["n"]) / len(values) for stats in pairs.values()),
        default=1.0,
    )
    bootstrap = _bootstrap(values, 2026092001 + len(values) + int(round(sum(values))))
    return {
        "test_trades_min_500": len(values) >= MIN_RUN_TRADES,
        "series_min_3": len(eligible) >= MIN_SERIES,
        "positive_series_min_3": len(positive) >= MIN_POSITIVE_SERIES,
        "pair_observation_concentration_lte_80pct": concentration <= MAX_PAIR_OBSERVATION_SHARE,
        "expectancy_positive": bool(
            base["expectancy_pips"] is not None
            and float(base["expectancy_pips"]) > 0.0
        ),
        "profit_factor_gt_1": bool(
            base["profit_factor"] is not None
            and float(base["profit_factor"]) > 1.0
        ),
        "drawdown_recovery_ratio_ge_1": bool(
            base["recovery_ratio"] is not None
            and float(base["recovery_ratio"]) >= MIN_RECOVERY_RATIO
        ),
        "ordinary_bootstrap_lower_positive": bootstrap["ordinary_lower_95_mean"] > 0.0,
        "block_bootstrap_lower_positive": bootstrap["block_lower_95_mean"] > 0.0,
        "bootstrap_probability_positive_ge_95pct": bootstrap["ordinary_probability_positive_mean"] >= 0.95,
        "holm_adjusted_p_le_005": adjusted_pvalue <= HOLM_ALPHA,
    }


def _variant_values(
    records: Sequence[Mapping[str, Any]],
    horizon: int,
    k: int,
) -> list[dict[str, Any]]:
    matched = [
        record
        for record in records
        if str(record["global_split"]) == "confirmation"
        and int(record["horizon"]) == horizon
        and int(record["k"]) == k
        and str(record["direction"]) in {"long", "short"}
    ]
    return sorted(
        [dict(record) for record in matched],
        key=lambda record: (_timestamp(record), str(record["pair"])),
    )


def evaluate_parameter_stability(
    candidate: Mapping[str, Any],
    all_records: Sequence[Mapping[str, Any]],
    timeline_records: Sequence[Mapping[str, Any]],
    folds: Sequence[PurgedFold],
) -> dict[str, Any]:
    horizon = int(candidate["horizon"])
    selected_k = int(candidate["k"])
    variants = [k for k in K_VALUES if k != selected_k]
    results: list[dict[str, Any]] = []
    for k in variants:
        matched = _variant_values(all_records, horizon, k)
        variant_folds = build_purged_folds(
            matched,
            horizon,
            len(folds),
            timeline_records=timeline_records,
        )
        model_results: list[dict[str, Any]] = []
        variant_pass = len(variant_folds) == len(folds)
        for name, model in EXECUTION_MODELS:
            fold_results: list[dict[str, Any]] = []
            for fold in variant_folds:
                values = _execution_values(list(fold.records), model)
                stats = _stats(values)
                fold_results.append(
                    {
                        "fold_id": fold.fold_id,
                        "statistics": stats,
                        "passes": (
                            stats["n"] >= MIN_RUN_TRADES
                            and stats["expectancy_pips"] is not None
                            and float(stats["expectancy_pips"]) > 0.0
                            and stats["profit_factor"] is not None
                            and float(stats["profit_factor"]) > 1.0
                        ),
                    }
                )
            aggregate = _stats(_execution_values(matched, model))
            model_pass = (
                len(fold_results) == len(folds)
                and all(item["passes"] for item in fold_results)
                and aggregate["n"] >= MIN_RUN_TRADES
                and aggregate["expectancy_pips"] is not None
                and float(aggregate["expectancy_pips"]) > 0.0
                and aggregate["profit_factor"] is not None
                and float(aggregate["profit_factor"]) > 1.0
            )
            variant_pass = variant_pass and model_pass
            model_results.append(
                {
                    "execution_model": name,
                    "aggregate": aggregate,
                    "folds": fold_results,
                    "passes": model_pass,
                }
            )
        results.append(
            {
                "variant_k": k,
                "matched_observations": len(matched),
                "execution_models": model_results,
                "passed": variant_pass,
            }
        )
    return {
        "selected_k": selected_k,
        "variant_count": len(results),
        "all_variants_pass": all(item["passed"] for item in results),
        "variants": results,
    }


def certify(
    discovery_report: Mapping[str, Any],
    confirmation_report: Mapping[str, Any],
    all_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if discovery_report.get("status") != "BIDIRECTIONAL_ANALOGUE_DISCOVERY_COMPLETED":
        raise ValueError("discovery report is not a completed bidirectional discovery")
    policy = discovery_report.get("selection_policy")
    if not isinstance(policy, Mapping) or policy.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("discovery report uses an unsupported bidirectional discovery contract")
    if confirmation_report.get("confirmation_contract_version") != CONFIRMATION_CONTRACT_VERSION:
        raise ValueError("confirmation report uses an unsupported bidirectional confirmation contract")
    if confirmation_report.get("state") != "PASS":
        return {
            "state": "INCOMPLETE",
            "reason": "bidirectional confirmation did not pass; strict certification is blocked",
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    candidates = discovery_report.get("top_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("discovery report has no candidate")
    selected_candidate = dict(candidates[0])
    candidate = _canonical_candidate(selected_candidate)
    if selected_candidate.get("candidate_fingerprint") != candidate_fingerprint(selected_candidate):
        raise ValueError("discovery candidate fingerprint is internally inconsistent")
    if confirmation_report.get("candidate_fingerprint") != candidate_fingerprint(candidate):
        raise ValueError("confirmation fingerprint does not match the frozen candidate")
    if candidate_identity(confirmation_report.get("candidate", {})) != candidate:
        raise ValueError("confirmation candidate identity does not match discovery candidate")

    discovery_binding = discovery_report.get("orchestration_binding")
    confirmation_binding = confirmation_report.get("orchestration_binding")
    if not isinstance(discovery_binding, Mapping) or not isinstance(confirmation_binding, Mapping):
        raise ValueError("discovery and confirmation artifacts require immutable orchestration bindings")
    for key in ("discovery_head_sha", "discovery_run_id", "source_run_id", "sample_stride", "history_states"):
        if discovery_binding.get(key) != confirmation_binding.get(key):
            raise ValueError(f"orchestration binding mismatch for {key}")
    if discovery_report.get("global_split_cutoff") != confirmation_report.get("global_split_cutoff"):
        raise ValueError("global split cutoff mismatch between discovery and confirmation evidence")

    candidate_records = [
        record
        for record in all_records
        if _candidate_matches(record, selected_candidate)
    ]
    confirmation_timeline = [
        record
        for record in all_records
        if str(record["global_split"]) == "confirmation"
    ]
    if not confirmation_timeline:
        return {
            "state": "INCOMPLETE",
            "reason": "no confirmation timeline is available for strict purged certification",
            "candidate": selected_candidate,
            "candidate_fingerprint": candidate_fingerprint(selected_candidate),
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    folds = build_purged_folds(
        candidate_records,
        int(candidate["horizon"]),
        FOLDS,
        timeline_records=confirmation_timeline,
    )
    if len(folds) != FOLDS:
        return {
            "state": "INCOMPLETE",
            "reason": "confirmation candidate cannot form twelve purged chronological runs",
            "candidate": selected_candidate,
            "candidate_fingerprint": candidate_fingerprint(selected_candidate),
            "fold_count": len(folds),
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }
    fold_counts = [len(fold.records) for fold in folds]
    if any(count < 2 for count in fold_counts):
        return {
            "state": "INCOMPLETE",
            "reason": "one or more certification folds has fewer than two observations",
            "candidate": selected_candidate,
            "candidate_fingerprint": candidate_fingerprint(selected_candidate),
            "fold_count": len(folds),
            "fold_observation_counts": fold_counts,
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    cells: list[dict[str, Any]] = []
    raw_pvalues: list[float] = []
    for fold in folds:
        for model_name, model in EXECUTION_MODELS:
            records = list(fold.records)
            values = _execution_values(records, model)
            raw_pvalue = hac_mean_pvalue(values)
            raw_pvalues.append(raw_pvalue)
            cells.append(
                {
                    "fold_id": fold.fold_id,
                    "execution_model": model_name,
                    "execution_cost_pips": model.total_cost_pips(),
                    "statistics": _stats(values),
                    "series_breakdown": _pair_stats(records, values),
                    "raw_hac_one_sided_pvalue": raw_pvalue,
                }
            )

    adjusted = holm_bonferroni(raw_pvalues)
    certification_cells: list[dict[str, Any]] = []
    index = 0
    for cell in cells:
        adjusted_pvalue = adjusted[index]
        index += 1
        values = _execution_values(
            list(folds[cell["fold_id"]].records),
            next(
                model
                for name, model in EXECUTION_MODELS
                if name == cell["execution_model"]
            ),
        )
        gates = _run_gates(list(folds[cell["fold_id"]].records), values, adjusted_pvalue)
        certification_cells.append(
            {
                **cell,
                "statistics": _stats(values),
                "series_breakdown": _pair_stats(list(folds[cell["fold_id"]].records), values),
                "holm_adjusted_pvalue": adjusted_pvalue,
                "gates": gates,
                "qualifies": all(gates.values()),
            }
        )

    certification_runs: list[dict[str, Any]] = []
    for fold in folds:
        fold_cells = [cell for cell in certification_cells if cell["fold_id"] == fold.fold_id]
        test_trade_count = fold_cells[0]["statistics"]["n"] if fold_cells else 0
        qualifies = (
            len(fold_cells) == len(EXECUTION_MODELS)
            and test_trade_count >= MIN_RUN_TRADES
            and all(cell["qualifies"] for cell in fold_cells)
        )
        certification_runs.append(
            {
                "run_id": fold.fold_id + 1,
                "fold_id": fold.fold_id,
                "test_trade_count": test_trade_count,
                "purged_at_start": fold.purged_at_start,
                "purged_at_end": fold.purged_at_end,
                "execution_model_results": fold_cells,
                "qualifies": qualifies,
            }
        )

    stability = evaluate_parameter_stability(
        selected_candidate,
        all_records,
        confirmation_timeline,
        folds,
    )
    realistic_model = next(
        model
        for name, model in EXECUTION_MODELS
        if name == "realistic_plus"
    )
    aggregate_values = [
        value
        for fold in folds
        for value in _execution_values(list(fold.records), realistic_model)
    ]
    aggregate_stats = _stats(aggregate_values)
    qualifying_runs = sum(run["qualifies"] for run in certification_runs)

    gates = {
        "exactly_12_qualifying_runs": qualifying_runs == 12,
        "three_execution_models": len(EXECUTION_MODELS) >= 3,
        "twelve_purged_walk_forward_runs": len(folds) == 12,
        "min_500_trades_per_run": all(
            run["test_trade_count"] >= MIN_RUN_TRADES
            for run in certification_runs
        ),
        "min_3_series_per_run": all(
            all(
                sum(
                    int(result["n"]) >= MIN_SERIES_TRADES
                    for result in cell["series_breakdown"].values()
                ) >= MIN_SERIES
                for cell in run["execution_model_results"]
            )
            for run in certification_runs
        ),
        "min_3_positive_series_per_run": all(
            all(
                sum(
                    int(result["n"]) >= MIN_SERIES_TRADES
                    and result["expectancy_pips"] is not None
                    and float(result["expectancy_pips"]) > 0.0
                    and result["profit_factor"] is not None
                    and float(result["profit_factor"]) > 1.0
                    for result in cell["series_breakdown"].values()
                ) >= MIN_POSITIVE_SERIES
                for cell in run["execution_model_results"]
            )
            for run in certification_runs
        ),
        "purged_walk_forward_stability": all(
            all(
                cell["statistics"]["expectancy_pips"] is not None
                and float(cell["statistics"]["expectancy_pips"]) > 0.0
                for cell in run["execution_model_results"]
            )
            for run in certification_runs
        ),
        "parameter_stability": bool(stability["all_variants_pass"]),
        "drawdown_recovery": all(
            all(
                cell["statistics"]["recovery_ratio"] is not None
                and float(cell["statistics"]["recovery_ratio"]) >= MIN_RECOVERY_RATIO
                for cell in run["execution_model_results"]
            )
            for run in certification_runs
        ),
        "bootstrap_robustness": all(
            all(
                cell["gates"]["ordinary_bootstrap_lower_positive"]
                and cell["gates"]["block_bootstrap_lower_positive"]
                and cell["gates"]["bootstrap_probability_positive_ge_95pct"]
                for cell in run["execution_model_results"]
            )
            for run in certification_runs
        ),
        "multiple_testing_holm": all(
            all(cell["gates"]["holm_adjusted_p_le_005"] for cell in run["execution_model_results"])
            for run in certification_runs
        ),
        "execution_cost_robustness": all(
            all(
                cell["statistics"]["expectancy_pips"] is not None
                and float(cell["statistics"]["expectancy_pips"]) > 0.0
                for cell in run["execution_model_results"]
            )
            for run in certification_runs
        ),
        "aggregate_realistic_model_positive": (
            aggregate_stats["expectancy_pips"] is not None
            and float(aggregate_stats["expectancy_pips"]) > 0.0
        ),
        "aggregate_realistic_model_pf_gt1": (
            aggregate_stats["profit_factor"] is not None
            and float(aggregate_stats["profit_factor"]) > 1.0
        ),
    }
    passed = all(gates.values())
    return {
        "state": "PASS" if passed else "FAIL",
        "reason": (
            "all predefined bidirectional purged certification requirements passed"
            if passed
            else "one or more predefined bidirectional purged certification requirements failed"
        ),
        "candidate": selected_candidate,
        "candidate_identity": candidate,
        "candidate_fingerprint": candidate_fingerprint(selected_candidate),
        "candidate_selection_rule": "rank-1 bidirectional discovery candidate is frozen; certification never selects an alternate candidate",
        "fold_contract": {
            "fold_count": FOLDS,
            "run_count": FOLDS,
            "purge_bars": int(candidate["horizon"]),
            "purge_interval": f'{int(candidate["horizon"]) * 10} minutes',
            "boundary_rule": "predeclared chronological confirmation timeline; each fold begins after a horizon purge and every target outcome must finish strictly before the next boundary",
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
        "fold_observation_counts": fold_counts,
        "certification_runs": certification_runs,
        "qualifying_run_count": qualifying_runs,
        "parameter_stability": stability,
        "aggregate_realistic_model": aggregate_stats,
        "multiple_testing_scope": "Holm correction across all 36 certification cells (12 folds x 3 execution models)",
        "gates": gates,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def run(
    input_dir: Path,
    discovery_report_path: Path,
    confirmation_report_path: Path,
    sample_stride: int,
    history_states: int,
    parallel_workers: int = 4,
) -> dict[str, Any]:
    discovery_report = json.loads(
        discovery_report_path.read_text(encoding="utf-8")
    )
    confirmation_report = json.loads(
        confirmation_report_path.read_text(encoding="utf-8")
    )
    discovery_binding = discovery_report.get("orchestration_binding")
    if not isinstance(discovery_binding, Mapping):
        raise ValueError("discovery report has no immutable orchestration binding")
    if int(discovery_binding["sample_stride"]) != sample_stride:
        raise ValueError("certification sample_stride does not match discovery binding")
    if int(discovery_binding["history_states"]) != history_states:
        raise ValueError("certification history_states does not match discovery binding")

    records, source_manifest, quality, cutoff = rebuild_target_records(
        input_dir,
        sample_stride,
        history_states,
        parallel_workers,
    )
    if cutoff != discovery_report.get("global_split_cutoff"):
        raise ValueError("rebuilt global split cutoff does not match discovery evidence")
    if source_manifest != discovery_report.get("source_manifest"):
        raise ValueError("rebuilt source SHA-256 manifest does not match discovery evidence")

    result = certify(discovery_report, confirmation_report, records)
    result.update(
        {
            "certification_contract_version": "v1-bidirectional-analogue-certification",
            "global_split_cutoff": cutoff,
            "source_manifest": source_manifest,
            "data_quality": quality,
            "orchestration_binding": {
                "discovery_run_id": int(discovery_binding["discovery_run_id"]),
                "discovery_head_sha": str(discovery_binding["discovery_head_sha"]),
                "source_run_id": int(discovery_binding["source_run_id"]),
                "sample_stride": sample_stride,
                "history_states": history_states,
            },
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run strict 12-run purged certification on the frozen bidirectional candidate."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--discovery-report", required=True)
    parser.add_argument("--confirmation-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--parallel-workers", type=int, default=4)
    args = parser.parse_args()
    result = run(
        Path(args.input_dir),
        Path(args.discovery_report),
        Path(args.confirmation_report),
        args.sample_stride,
        args.history_states,
        args.parallel_workers,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"BIDIRECTIONAL_CERTIFICATION_STATE={result['state']}")
    print(f"QUALIFYING_RUN_COUNT={result.get('qualifying_run_count', 0)}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
