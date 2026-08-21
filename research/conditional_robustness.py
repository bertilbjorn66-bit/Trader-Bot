from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean


def stats(values: list[float]) -> dict[str, float | int | None] | None:
    if not values:
        return None
    wins = sum(value > 0.0 for value in values)
    gross_wins = sum(value for value in values if value > 0.0)
    gross_losses = -sum(value for value in values if value < 0.0)
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "n": len(values),
        "expectancy_pips": mean(values),
        "profit_factor": gross_wins / gross_losses if gross_losses else None,
        "win_rate": wins / len(values),
        "max_drawdown_pips": drawdown,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit enriched conditional finalists on untouched confirmation data.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    finalists = data["confirmation_finalists"]
    records = data["target_records"]
    results: list[dict[str, object]] = []

    for finalist in finalists:
        chosen = [
            record
            for record in records
            if record["horizon"] == finalist["horizon"]
            and record["regime"] == finalist["regime"]
            and (finalist["pairset"] == "all" or str(record["pair"]).endswith("/JPY"))
            and record["split"] == "confirmation"
            and (finalist["distance_max"] is None or record["median_distance"] <= finalist["distance_max"])
            and record["agreement"] >= finalist["agreement_min"]
        ]
        by_pair: dict[str, list[float]] = {}
        by_year: dict[str, list[float]] = {}
        by_direction: dict[str, list[float]] = {}
        for record in chosen:
            value = float(record["outcome_pips"])
            by_pair.setdefault(str(record["pair"]), []).append(value)
            by_year.setdefault(str(record["year"]), []).append(value)
            by_direction.setdefault(str(record["direction"]), []).append(value)

        confirmation = stats([float(record["outcome_pips"]) for record in chosen])
        pair_stats = {key: stats(values) for key, values in by_pair.items()}
        year_stats = {key: stats(values) for key, values in by_year.items()}
        direction_stats = {key: stats(values) for key, values in by_direction.items()}
        stress = {
            str(cost): stats([float(record["outcome_pips"]) - cost for record in chosen])
            for cost in (0.0, 0.2, 0.5, 1.0)
        }
        positive_pairs = sum(
            1
            for result in pair_stats.values()
            if result and result["expectancy_pips"] > 0.0 and result["profit_factor"] is not None and result["profit_factor"] > 1.0
        )
        promotion_gate = {
            "confirmation_pf_gt_1": bool(confirmation and confirmation["profit_factor"] and confirmation["profit_factor"] > 1.0),
            "confirmation_expectancy_positive": bool(confirmation and confirmation["expectancy_pips"] > 0.0),
            "confirmation_sample_min_100": bool(confirmation and confirmation["n"] >= 100),
            "stress_0_5_pips_positive": bool(
                stress["0.5"]
                and stress["0.5"]["expectancy_pips"] > 0.0
                and stress["0.5"]["profit_factor"] is not None
                and stress["0.5"]["profit_factor"] > 1.0
            ),
            "positive_pair_count_min_2": positive_pairs >= 2,
            "max_drawdown_recorded": bool(confirmation and confirmation["max_drawdown_pips"] is not None),
        }
        results.append({
            "candidate": finalist,
            "confirmation": confirmation,
            "stress": stress,
            "pair_breakdown": pair_stats,
            "year_breakdown": year_stats,
            "direction_breakdown": direction_stats,
            "positive_pair_count": positive_pairs,
            "promotion_gate": promotion_gate,
            "promotion_eligible": all(promotion_gate.values()),
        })

    output = {
        "status": "CONDITIONAL_ROBUSTNESS_AUDIT_COMPLETED",
        "promotion_policy": "No live execution authorization. Promotion requires every gate to pass plus a separate paper-trading period and independent review.",
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
