from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

PAIR_PIP = {
    "EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01,
    "AUD/USD": 0.0001, "USD/CAD": 0.0001, "USD/CHF": 0.0001,
    "NZD/USD": 0.0001, "EUR/JPY": 0.01, "GBP/JPY": 0.01,
}


def wilson_interval(win_rate: float, n: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    denominator = 1.0 + (z * z / n)
    centre = (win_rate + z * z / (2.0 * n)) / denominator
    half = z * math.sqrt((win_rate * (1.0 - win_rate) / n) + (z * z / (4.0 * n * n))) / denominator
    return centre - half, centre + half


def inverted_profit_factor(win_rate: float, avg_win: float, avg_loss: float) -> float | None:
    if avg_win <= 0.0 or avg_loss >= 0.0 or not 0.0 < win_rate < 1.0:
        return None
    return ((1.0 - win_rate) * (-avg_loss)) / (win_rate * avg_win)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit an existing empirical report without market-data access.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-group-sample", type=int, default=150)
    args = parser.parse_args()
    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if source.get("research_status") != "EMPIRICAL_DATAFEED_RUN_COMPLETED":
        raise SystemExit("Input is not a completed empirical datafeed report")
    if source.get("synthetic") is not False or source.get("empirical") is not True:
        raise SystemExit("Input must be empirical-only and non-synthetic")
    pairs = source.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 9:
        raise SystemExit("Expected the completed nine-pair report")

    cells: list[dict[str, Any]] = []
    baseline: list[dict[str, Any]] = []
    for pair_report in pairs:
        pair = str(pair_report["pair"])
        pip = PAIR_PIP[pair]
        for horizon_text, horizon in pair_report["horizons"].items():
            oos = horizon["sequential_out_of_sample"]
            expectancy = float(oos["expectancy"])
            win_rate = float(oos["win_rate"])
            avg_win = float(oos["avg_win"])
            avg_loss = float(oos["avg_loss"])
            baseline.append({
                "pair": pair,
                "horizon": int(horizon_text),
                "targets": int(oos["n"]),
                "expectancy_pips": expectancy / pip,
                "profit_factor": float(oos["profit_factor"]),
                "win_rate": win_rate,
                "inverted_expectancy_pips": -expectancy / pip,
                "inverted_profit_factor": inverted_profit_factor(win_rate, avg_win, avg_loss),
            })
        grouped = pair_report.get("grouped_sequential_results", {})
        for group, horizons in grouped.items():
            for horizon_text, result in horizons.items():
                n = int(result["n"])
                win_rate = float(result["win_rate"])
                low, high = wilson_interval(win_rate, n)
                expectancy = float(result["expectancy"])
                avg_win = float(result["avg_win"])
                avg_loss = float(result["avg_loss"])
                cells.append({
                    "pair": pair,
                    "group": group,
                    "horizon": int(horizon_text),
                    "n": n,
                    "expectancy_pips": expectancy / pip,
                    "profit_factor": float(result["profit_factor"]),
                    "win_rate": win_rate,
                    "win_rate_ci_low": low,
                    "win_rate_ci_high": high,
                    "inverted_expectancy_pips": -expectancy / pip,
                    "inverted_profit_factor": inverted_profit_factor(win_rate, avg_win, avg_loss),
                })

    eligible = [cell for cell in cells if cell["n"] >= args.min_group_sample]
    survivors = [cell for cell in eligible if cell["expectancy_pips"] > 0.0 and cell["profit_factor"] > 1.0]
    strict_ci_survivors = [
        cell for cell in survivors
        if cell["win_rate_ci_low"] is not None and cell["win_rate_ci_low"] > 0.50
    ]

    aggregate: defaultdict[tuple[str, int], dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "weighted_expectancy": 0.0, "win_value": 0.0, "loss_value": 0.0, "positive_pairs": 0, "pf_gt1_pairs": 0}
    )
    for cell in eligible:
        key = (cell["group"], cell["horizon"])
        item = aggregate[key]
        item["n"] += cell["n"]
        item["weighted_expectancy"] += cell["expectancy_pips"] * cell["n"]
        pip = PAIR_PIP[cell["pair"]]
        result = next(
            r["grouped_sequential_results"][cell["group"]][str(cell["horizon"])]
            for r in pairs if r["pair"] == cell["pair"]
        )
        item["win_value"] += cell["n"] * cell["win_rate"] * float(result["avg_win"]) / pip
        item["loss_value"] += cell["n"] * (1.0 - cell["win_rate"]) * (-float(result["avg_loss"])) / pip
        item["positive_pairs"] += int(cell["expectancy_pips"] > 0.0)
        item["pf_gt1_pairs"] += int(cell["profit_factor"] > 1.0)

    aggregate_rows = []
    for (group, horizon), item in aggregate.items():
        aggregate_rows.append({
            "group": group,
            "horizon": horizon,
            "n": item["n"],
            "weighted_expectancy_pips": item["weighted_expectancy"] / item["n"],
            "aggregate_profit_factor": item["win_value"] / item["loss_value"] if item["loss_value"] else None,
            "positive_pairs": item["positive_pairs"],
            "pf_gt1_pairs": item["pf_gt1_pairs"],
        })
    aggregate_rows.sort(key=lambda row: (row["aggregate_profit_factor"] or -math.inf, row["weighted_expectancy_pips"]), reverse=True)

    inversion_candidates = [
        row for row in baseline
        if row["inverted_expectancy_pips"] > 0.0
        and row["inverted_profit_factor"] is not None
        and row["inverted_profit_factor"] > 1.0
    ]
    inversion_candidates.sort(key=lambda row: (row["inverted_profit_factor"], row["inverted_expectancy_pips"]), reverse=True)

    output = {
        "audit_status": "EMPIRICAL_RESULT_AUDIT_COMPLETED",
        "source_report_generated_at": source.get("generated_at"),
        "source_research_status": source.get("research_status"),
        "market_data_accessed": False,
        "datasets_accessed": False,
        "pair_count": len(pairs),
        "minimum_group_sample": args.min_group_sample,
        "normalization": "price-unit expectancy converted to quote-currency pips; profit factor remains unitless",
        "baseline": baseline,
        "conditional_cells_total": len(cells),
        "conditional_cells_eligible": len(eligible),
        "conditional_cells_positive_expectancy": sum(cell["expectancy_pips"] > 0.0 for cell in eligible),
        "conditional_cells_profit_factor_gt1": sum(cell["profit_factor"] > 1.0 for cell in eligible),
        "conditional_survivors": sorted(survivors, key=lambda row: (row["profit_factor"], row["expectancy_pips"]), reverse=True),
        "strict_ci_survivors": sorted(strict_ci_survivors, key=lambda row: (row["profit_factor"], row["expectancy_pips"]), reverse=True),
        "aggregate_group_rankings": aggregate_rows,
        "direction_inversion_candidates": inversion_candidates[:30],
        "interpretation": {
            "baseline": "The unconditional directional analogue rule remains negative out of sample across all nine pairs and four horizons.",
            "conditional": "The completed report contains conditional pockets of positive expectancy, most notably high_volatility_range on EUR/JPY and GBP/JPY at horizons 3-6, plus several year-specific cells.",
            "strict_ci": "A strict exploratory screen requires the Wilson 95% lower bound of win rate to exceed 50%; this is a diagnostic screen, not a proof of profitability or statistical independence.",
            "robustness": "These are discovery signals, not validated strategies. Regime/session/year grouping creates multiple comparisons, and the report lacks per-target observations needed for bootstrap confidence intervals or true multiple-testing control.",
            "analogue_quality_limit": "The final artifact retains average analogue count and probability calibration but not per-target analogue distances, agreement bins, or thresholded predictions. The enriched experiment changes that output schema.",
            "direction_limit": "The inversion candidates are diagnostic only. The final report does not retain separate long/short outcomes, so inversion is a hypothetical sign-flip test rather than proof that the momentum direction rule should be reversed.",
        },
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
