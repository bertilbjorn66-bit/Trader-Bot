from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from research.cftc_positioning_discovery import (
    PAIR_CURRENCY,
    PAIR_PIP,
    _build_daily_bars,
    _index_daily,
    _safe_hac,
    build_feature_panel,
    load_positions,
)
from research.intelligence_controls import ExecutionCostModel
from research.multiple_testing import holm_bonferroni
from research.non_live_evaluation import block_bootstrap_means, bootstrap_means, max_drawdown, profit_factor

FOLDS = 12
MIN_RUN_OBSERVATIONS = 30
MIN_PAIR_OBSERVATIONS = 8
MIN_POSITIVE_PAIRS = 3
MAX_PAIR_CONCENTRATION = 0.80
BOOTSTRAP_REPS = 2000
HOLM_ALPHA = 0.05
MIN_RECOVERY_RATIO = 1.0
PARAMETER_PERTURBATIONS = (-0.10, -0.05, 0.05, 0.10)
EXECUTION_MODELS: tuple[tuple[str, ExecutionCostModel], ...] = (
    ("nominal_plus", ExecutionCostModel(spread_pips=0.0, slippage_pips=0.20, latency_pips=0.20)),
    ("realistic_plus", ExecutionCostModel(spread_pips=0.0, slippage_pips=0.50, latency_pips=0.30)),
    ("adverse_plus", ExecutionCostModel(spread_pips=0.0, slippage_pips=1.00, latency_pips=0.50)),
)
CONTRACT_VERSION = "v1-cftc-positioning-12-run-purged-certification"


@dataclass(frozen=True)
class TradeRecord:
    entry_day: date
    target_day: date
    pair: str
    value_pips: float


@dataclass(frozen=True)
class CertificationFold:
    fold_id: int
    start: date
    end: date | None
    records: tuple[TradeRecord, ...]
    purged_start_days: int
    purged_end_records: int


def candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {
            key: candidate[key]
            for key in ("feature_type", "feature_window", "threshold", "orientation", "horizon")
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _signal_days(
    positions: Mapping[str, Sequence[Any]],
    daily: Mapping[str, Sequence[Any]],
) -> list[date]:
    report_dates = sorted(
        set().union(*(set(item.report_date for item in positions[currency]) for currency in positions))
    )
    common_daily = sorted(
        set.intersection(*(set(item.day for item in daily[pair]) for pair in daily))
    )
    signal_days: list[date] = []
    for report_day in report_dates:
        desired = report_day + timedelta(days=(7 - report_day.weekday()) % 7 or 7)
        candidate_days = [day for day in common_daily if day >= desired]
        if candidate_days:
            signal_days.append(candidate_days[0])
    return sorted(set(signal_days))


def _candidate_trade_records(
    candidate: Mapping[str, Any],
    panel: Mapping[date, Mapping[str, float]],
    daily: Mapping[str, Sequence[Any]],
    indices: Mapping[str, Mapping[date, int]],
    signal_days: Sequence[date],
) -> list[TradeRecord]:
    feature_type = str(candidate["feature_type"])
    feature_window = int(candidate["feature_window"])
    threshold = float(candidate["threshold"])
    orientation = str(candidate["orientation"])
    horizon = int(candidate["horizon"])
    records: list[TradeRecord] = []

    for entry_day in signal_days:
        desired_report = entry_day - timedelta(days=6)
        if desired_report not in panel:
            candidates = [
                report_day
                for report_day in panel
                if report_day <= entry_day and report_day.weekday() == 1
            ]
            if not candidates:
                continue
            report_day = max(candidates)
        else:
            report_day = desired_report

        features = panel.get(report_day, {})
        for pair, (base, quote) in PAIR_CURRENCY.items():
            base_score = features.get(f"{base}:{feature_type}:{feature_window}")
            quote_score = features.get(f"{quote}:{feature_type}:{feature_window}")
            if base_score is None or quote_score is None:
                continue
            score = float(base_score) - float(quote_score)
            if not math.isfinite(score) or abs(score) < threshold:
                continue

            index = indices[pair].get(entry_day)
            if index is None or index + horizon - 1 >= len(daily[pair]):
                continue
            entry = daily[pair][index]
            target = daily[pair][index + horizon - 1]
            direction = 1 if score > 0 else -1
            if orientation == "reversion":
                direction *= -1
            movement = (
                (target.bid_close - entry.ask_open) / PAIR_PIP[pair]
                if direction > 0
                else (entry.bid_open - target.ask_close) / PAIR_PIP[pair]
            )
            records.append(
                TradeRecord(
                    entry_day=entry_day,
                    target_day=target.day,
                    pair=pair,
                    value_pips=float(movement),
                )
            )
    return records


def build_purged_folds(
    records: Sequence[TradeRecord],
    signal_days: Sequence[date],
    horizon: int,
    folds: int = FOLDS,
) -> list[CertificationFold]:
    ordered_days = sorted(set(signal_days))
    if folds != FOLDS or len(ordered_days) < folds:
        return []

    boundaries = [
        ordered_days[(len(ordered_days) * index) // folds]
        for index in range(folds)
    ]
    boundaries.append(ordered_days[-1] + timedelta(days=1))

    day_index = {day: index for index, day in enumerate(ordered_days)}
    result: list[CertificationFold] = []
    for fold_id in range(folds):
        start = boundaries[fold_id]
        end = None if fold_id == folds - 1 else boundaries[fold_id + 1]
        start_index = day_index[start]
        safe_records: list[TradeRecord] = []
        purged_start_days = 0
        purged_end_records = 0

        for record in records:
            if not (record.entry_day >= start and (end is None or record.entry_day < end)):
                continue
            record_index = day_index[record.entry_day]
            if record_index < start_index + horizon:
                purged_start_days += 1
                continue
            if end is not None and record.target_day >= end:
                purged_end_records += 1
                continue
            safe_records.append(record)

        result.append(
            CertificationFold(
                fold_id=fold_id,
                start=start,
                end=end,
                records=tuple(
                    sorted(safe_records, key=lambda item: (item.entry_day, item.pair))
                ),
                purged_start_days=purged_start_days,
                purged_end_records=purged_end_records,
            )
        )
    return result


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "expectancy_pips": None,
            "profit_factor": None,
            "max_drawdown_pips": None,
            "recovery_ratio": None,
            "ordinary_bootstrap_lower": None,
            "block_bootstrap_lower": None,
            "probability_positive": 0.0,
            "hac_one_sided_pvalue": 1.0,
        }

    expectancy = mean(values)
    drawdown = max_drawdown(values)
    net = sum(values)
    recovery = math.inf if drawdown == 0.0 and net > 0.0 else (
        net / drawdown if drawdown > 0.0 else 0.0
    )
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=20261003)
    block = block_bootstrap_means(
        values,
        block_size=min(5, len(values)),
        reps=BOOTSTRAP_REPS,
        seed=20261004,
    )
    return {
        "n": len(values),
        "expectancy_pips": expectancy,
        "profit_factor": profit_factor(values),
        "max_drawdown_pips": drawdown,
        "recovery_ratio": recovery,
        "ordinary_bootstrap_lower": ordinary[49],
        "block_bootstrap_lower": block[49],
        "probability_positive": mean(value > 0.0 for value in ordinary),
        "hac_one_sided_pvalue": _safe_hac(values),
    }


def _pair_stats(
    records: Sequence[TradeRecord],
    values: Sequence[float],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for record, value in zip(records, values, strict=True):
        grouped.setdefault(record.pair, []).append(value)
    return {pair: _stats(pair_values) for pair, pair_values in sorted(grouped.items())}


def _cell_gates(
    records: Sequence[TradeRecord],
    values: Sequence[float],
    adjusted_p: float,
) -> dict[str, bool]:
    stats = _stats(values)
    pairs = _pair_stats(records, values)
    eligible = {
        pair: result
        for pair, result in pairs.items()
        if result["n"] >= MIN_PAIR_OBSERVATIONS
    }
    positive = {
        pair: result
        for pair, result in eligible.items()
        if result["expectancy_pips"] > 0.0
        and result["profit_factor"] is not None
        and result["profit_factor"] > 1.0
    }
    concentration = max(
        (result["n"] / len(values) for result in pairs.values()),
        default=1.0,
    )
    return {
        "min_observations": len(values) >= MIN_RUN_OBSERVATIONS,
        "min_pairs": len(eligible) >= MIN_POSITIVE_PAIRS,
        "min_positive_pairs": len(positive) >= MIN_POSITIVE_PAIRS,
        "pair_concentration_lte_80pct": concentration <= MAX_PAIR_CONCENTRATION,
        "expectancy_positive": bool(
            stats["expectancy_pips"] is not None and stats["expectancy_pips"] > 0.0
        ),
        "profit_factor_gt_1": bool(
            stats["profit_factor"] is not None and stats["profit_factor"] > 1.0
        ),
        "recovery_ratio_ge_1": bool(
            stats["recovery_ratio"] is not None
            and stats["recovery_ratio"] >= MIN_RECOVERY_RATIO
        ),
        "ordinary_bootstrap_lower_positive": bool(
            stats["ordinary_bootstrap_lower"] is not None
            and stats["ordinary_bootstrap_lower"] > 0.0
        ),
        "block_bootstrap_lower_positive": bool(
            stats["block_bootstrap_lower"] is not None
            and stats["block_bootstrap_lower"] > 0.0
        ),
        "bootstrap_probability_positive_ge_95pct": stats["probability_positive"] >= 0.95,
        "holm_adjusted_p_le_005": adjusted_p <= HOLM_ALPHA,
    }


def _execution_values(
    records: Sequence[TradeRecord],
    model: ExecutionCostModel,
) -> list[float]:
    cost = model.total_cost_pips()
    return [record.value_pips - cost for record in records]


def _parameter_stability(
    candidate: Mapping[str, Any],
    panel: Mapping[date, Mapping[str, float]],
    daily: Mapping[str, Sequence[Any]],
    indices: Mapping[str, Mapping[date, int]],
    confirmation_days: Sequence[date],
    folds: Sequence[CertificationFold],
) -> dict[str, Any]:
    base_threshold = float(candidate["threshold"])
    variants: list[dict[str, Any]] = []
    for delta in PARAMETER_PERTURBATIONS:
        variant = dict(candidate)
        variant["threshold"] = base_threshold * (1.0 + delta)
        variants.append(variant)

    results: list[dict[str, Any]] = []
    for index, variant in enumerate(variants):
        records = _candidate_trade_records(
            variant, panel, daily, indices, confirmation_days
        )
        variant_folds = build_purged_folds(
            records,
            confirmation_days,
            int(variant["horizon"]),
            len(folds),
        )
        model_results: list[dict[str, Any]] = []
        for model_name, model in EXECUTION_MODELS:
            fold_passes: list[bool] = []
            for fold in variant_folds:
                values = _execution_values(fold.records, model)
                stats = _stats(values)
                fold_passes.append(
                    bool(
                        len(values) >= MIN_RUN_OBSERVATIONS
                        and stats["expectancy_pips"] > 0.0
                        and stats["profit_factor"] is not None
                        and stats["profit_factor"] > 1.0
                        and stats["ordinary_bootstrap_lower"] > 0.0
                        and stats["block_bootstrap_lower"] > 0.0
                    )
                )
            model_results.append(
                {
                    "execution_model": model_name,
                    "fold_count": len(variant_folds),
                    "all_folds_pass": len(variant_folds) == len(folds)
                    and all(fold_passes),
                }
            )
        results.append(
            {
                "variant_index": index,
                "threshold": variant["threshold"],
                "execution_models": model_results,
                "passed": bool(model_results)
                and all(item["all_folds_pass"] for item in model_results),
            }
        )

    return {
        "variant_count": len(results),
        "all_variants_pass": all(item["passed"] for item in results),
        "variants": results,
    }


def certify(
    discovery_report: Mapping[str, Any],
    cftc_dir: Path,
    feed_dir: Path,
) -> dict[str, Any]:
    if discovery_report.get("status") != "CFTC_POSITIONING_DISCOVERY_COMPLETED":
        raise ValueError("unsupported discovery report state")
    if (
        discovery_report.get("selection_policy", {}).get("confirmation_used_for_selection")
        is not False
    ):
        raise ValueError("discovery report does not prove confirmation-free selection")
    if int(discovery_report.get("family_size", 0)) != 144:
        raise ValueError("unexpected CFTC family size")
    if int(discovery_report.get("candidate_count", 0)) == 0:
        return {
            "state": "INCOMPLETE",
            "reason": "fresh CFTC discovery produced no candidate",
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    confirmation = discovery_report.get("confirmation")
    if not isinstance(confirmation, Mapping) or confirmation.get("state") != "PASS":
        return {
            "state": "INCOMPLETE",
            "reason": "CFTC discovery candidate did not pass the untouched primary confirmation",
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    candidates = discovery_report.get("top_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("CFTC discovery report has no rank-1 candidate")
    candidate = dict(candidates[0])
    expected = candidate_fingerprint(candidate)
    if confirmation.get("candidate_fingerprint") not in (None, expected):
        raise ValueError("CFTC confirmation candidate fingerprint mismatch")

    positions, manifest = load_positions(cftc_dir)
    panel = build_feature_panel(positions)
    daily, feed_quality = _build_daily_bars(feed_dir)
    indices = _index_daily(daily)
    signal_days = _signal_days(positions, daily)
    split_cutoff = date.fromisoformat(str(discovery_report["global_split_cutoff"]))
    confirmation_days = [day for day in signal_days if day >= split_cutoff]
    records = _candidate_trade_records(
        candidate, panel, daily, indices, confirmation_days
    )
    folds = build_purged_folds(
        records, confirmation_days, int(candidate["horizon"]), FOLDS
    )
    if len(folds) != FOLDS:
        return {
            "state": "INCOMPLETE",
            "reason": "confirmation timeline cannot form twelve chronological purged folds",
            "candidate": candidate,
            "fold_count": len(folds),
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    fold_counts = [len(fold.records) for fold in folds]
    if any(count < MIN_RUN_OBSERVATIONS for count in fold_counts):
        return {
            "state": "INCOMPLETE",
            "reason": "one or more certification folds has too few observations",
            "candidate": candidate,
            "fold_observation_counts": fold_counts,
            "promotion_authorized": False,
            "live_execution_authorized": False,
        }

    raw_pvalues: list[float] = []
    payloads: list[dict[str, Any]] = []
    for fold in folds:
        for model_name, model in EXECUTION_MODELS:
            values = _execution_values(fold.records, model)
            raw = _safe_hac(values)
            raw_pvalues.append(raw)
            payloads.append(
                {
                    "fold_id": fold.fold_id,
                    "execution_model": model_name,
                    "cost_pips": model.total_cost_pips(),
                    "records": fold.records,
                    "values": values,
                    "raw_p": raw,
                }
            )

    adjusted = holm_bonferroni(raw_pvalues)
    cells: list[dict[str, Any]] = []
    for payload, adjusted_p in zip(payloads, adjusted, strict=True):
        records_for_cell = payload["records"]
        values = payload["values"]
        stats = _stats(values)
        gates = _cell_gates(records_for_cell, values, adjusted_p)
        cells.append(
            {
                "fold_id": payload["fold_id"],
                "execution_model": payload["execution_model"],
                "cost_pips": payload["cost_pips"],
                "statistics": stats,
                "pair_breakdown": _pair_stats(records_for_cell, values),
                "raw_hac_one_sided_pvalue": payload["raw_p"],
                "holm_adjusted_pvalue": adjusted_p,
                "gates": gates,
                "qualifies": all(gates.values()),
            }
        )

    runs: list[dict[str, Any]] = []
    for fold_id in range(FOLDS):
        fold_cells = [cell for cell in cells if cell["fold_id"] == fold_id]
        runs.append(
            {
                "run_id": fold_id + 1,
                "fold_id": fold_id,
                "test_observation_count": fold_counts[fold_id],
                "execution_model_results": fold_cells,
                "qualifies": len(fold_cells) == len(EXECUTION_MODELS)
                and all(cell["qualifies"] for cell in fold_cells),
            }
        )

    qualifying = sum(run["qualifies"] for run in runs)
    stability = _parameter_stability(
        candidate, panel, daily, indices, confirmation_days, folds
    )
    aggregate_realistic = [
        value
        for fold in folds
        for value in _execution_values(fold.records, EXECUTION_MODELS[1][1])
    ]
    aggregate = _stats(aggregate_realistic)

    gates = {
        "exactly_12_qualifying_runs": qualifying == FOLDS,
        "three_execution_models": len(EXECUTION_MODELS) == 3,
        "twelve_purged_folds": len(folds) == FOLDS,
        "min_observations_per_run": all(
            run["test_observation_count"] >= MIN_RUN_OBSERVATIONS for run in runs
        ),
        "parameter_stability": bool(stability["all_variants_pass"]),
        "all_run_cells_qualify": all(run["qualifies"] for run in runs),
        "aggregate_realistic_expectancy_positive": bool(
            aggregate["expectancy_pips"] is not None
            and aggregate["expectancy_pips"] > 0.0
        ),
        "aggregate_realistic_pf_gt_1": bool(
            aggregate["profit_factor"] is not None
            and aggregate["profit_factor"] > 1.0
        ),
    }
    passed = all(gates.values())

    return {
        "state": "PASS" if passed else "FAIL",
        "reason": "all CFTC certification gates passed"
        if passed
        else "one or more CFTC certification gates failed",
        "contract_version": CONTRACT_VERSION,
        "candidate": candidate,
        "candidate_fingerprint": expected,
        "fold_count": len(folds),
        "fold_observation_counts": fold_counts,
        "purge_horizon": int(candidate["horizon"]),
        "certification_runs": runs,
        "qualifying_run_count": qualifying,
        "parameter_stability": stability,
        "aggregate_realistic_model": aggregate,
        "gates": gates,
        "cftc_manifest": manifest,
        "feed_quality": feed_quality,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strict non-live CFTC positioning certification."
    )
    parser.add_argument("--discovery-report", required=True)
    parser.add_argument("--cftc-dir", required=True)
    parser.add_argument("--feed-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    discovery = json.loads(
        Path(args.discovery_report).read_text(encoding="utf-8")
    )
    result = certify(
        discovery,
        Path(args.cftc_dir),
        Path(args.feed_dir),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"CFTC_CERTIFICATION_STATE={result['state']}")
    print(f"QUALIFYING_RUN_COUNT={result.get('qualifying_run_count', 0)}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
