from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

MIN_CONFIRMATION_SAMPLES = 100
MIN_DISCOVERY_SAMPLES = math.ceil(MIN_CONFIRMATION_SAMPLES * 0.60 / 0.40)
MIN_HALF_SAMPLES = 50

Record = dict[str, Any]
Candidate = dict[str, Any]


def stats(values: list[float]) -> dict[str, Any]:
    wins = sum(value > 0.0 for value in values)
    gross_wins = sum(value for value in values if value > 0.0)
    gross_losses = -sum(value for value in values if value < 0.0)
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "n": len(values),
        "expectancy_pips": mean(values) if values else 0.0,
        "profit_factor": gross_wins / gross_losses if gross_losses else None,
        "win_rate": wins / len(values) if values else 0.0,
        "max_drawdown_pips": drawdown,
    }


def matches(record: Record, candidate: Candidate, split: str) -> bool:
    return (
        record["split"] == split
        and record["horizon"] == candidate["horizon"]
        and record["regime"] == candidate["regime"]
        and record["session"] == candidate["session"]
        and record["pair"] == candidate["pair"]
        and float(record["agreement"]) >= float(candidate["agreement_min"])
        and (
            candidate["distance_max"] is None
            or float(record["median_distance"]) <= float(candidate["distance_max"])
        )
    )


def evaluate(records: list[Record], candidate: Candidate, split: str) -> dict[str, Any] | None:
    chosen = [r for r in records if matches(r, candidate, split)]
    if not chosen:
        return None
    values = [float(r["outcome_pips"]) for r in chosen]
    result = stats(values)
    years: dict[str, list[float]] = defaultdict(list)
    directions: dict[str, list[float]] = defaultdict(list)
    for record in chosen:
        years[str(record["year"])].append(float(record["outcome_pips"]))
        directions[str(record["direction"])].append(float(record["outcome_pips"]))
    result["year_breakdown"] = {year: stats(vals) for year, vals in years.items()}
    result["direction_breakdown"] = {direction: stats(vals) for direction, vals in directions.items()}
    return result


def discovery_stable(result: dict[str, Any]) -> bool:
    years = result["year_breakdown"]
    positive_years = [
        value
        for value in years.values()
        if int(value["n"]) >= MIN_HALF_SAMPLES and float(value["expectancy_pips"]) > 0.0
    ]
    return (
        int(result["n"]) >= MIN_DISCOVERY_SAMPLES
        and float(result["expectancy_pips"]) > 0.0
        and result["profit_factor"] is not None
        and float(result["profit_factor"]) > 1.0
        and len(positive_years) >= 2
    )


def split_discovery_half(records: list[Record]) -> tuple[list[Record], list[Record]]:
    ordered = sorted(records, key=lambda r: datetime.fromisoformat(str(r["timestamp"])))
    cut = len(ordered) // 2
    return ordered[:cut], ordered[cut:]


def stressed_stats(values: list[float], extra_cost_pips: float) -> dict[str, Any]:
    return stats([value - extra_cost_pips for value in values])


def promotion_gate(confirmation: dict[str, Any] | None) -> dict[str, bool]:
    if confirmation is None:
        return {"confirmation_exists": False}
    years = confirmation["year_breakdown"]
    stable_years = sum(
        1
        for value in years.values()
        if int(value["n"]) >= 25 and float(value["expectancy_pips"]) > 0.0
    )
    values = confirmation["_values"]
    stress_02 = stressed_stats(values, 0.2)
    stress_05 = stressed_stats(values, 0.5)
    return {
        "confirmation_exists": True,
        "confirmation_sample_min_100": int(confirmation["n"]) >= MIN_CONFIRMATION_SAMPLES,
        "confirmation_expectancy_positive": float(confirmation["expectancy_pips"]) > 0.0,
        "confirmation_pf_gt_1": confirmation["profit_factor"] is not None and float(confirmation["profit_factor"]) > 1.0,
        "stress_0_2_positive": float(stress_02["expectancy_pips"]) > 0.0 and stress_02["profit_factor"] is not None and float(stress_02["profit_factor"]) > 1.0,
        "stress_0_5_positive": float(stress_05["expectancy_pips"]) > 0.0 and stress_05["profit_factor"] is not None and float(stress_05["profit_factor"]) > 1.0,
        "confirmation_temporally_stable": stable_years >= 2,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Second-cycle survival research using the immutable enriched target record set.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records: list[Record] = data["target_records"]

    grouped: dict[tuple[str, int, str, str, str], list[Record]] = defaultdict(list)
    for record in records:
        key = (
            str(record["pair"]),
            int(record["horizon"]),
            str(record["regime"]),
            str(record["session"]),
            str(record["split"]),
        )
        grouped[key].append(record)

    candidates: list[Candidate] = []
    pairs = sorted({key[0] for key in grouped})
    horizons = sorted({key[1] for key in grouped})
    regimes = sorted({key[2] for key in grouped})
    sessions = sorted({key[3] for key in grouped})

    for pair in pairs:
        for horizon in horizons:
            for agreement_min in (0.50, 0.60, 0.70):
                for distance_max in (None, 0.5, 1.0, 1.5, 2.0):
                    for regime in regimes:
                        for session in sessions:
                            discovery_records = grouped.get((pair, horizon, regime, session, "discovery"), [])
                            confirmation_records = grouped.get((pair, horizon, regime, session, "confirmation"), [])
                            if not discovery_records or len(confirmation_records) < MIN_CONFIRMATION_SAMPLES:
                                continue
                            candidate: Candidate = {
                                "pair": pair,
                                "horizon": horizon,
                                "agreement_min": agreement_min,
                                "distance_max": distance_max,
                                "regime": regime,
                                "session": session,
                            }
                            discovery = evaluate(discovery_records, candidate, "discovery")
                            if discovery is None or not discovery_stable(discovery):
                                continue
                            chosen = [r for r in discovery_records if matches(r, candidate, "discovery")]
                            first, second = split_discovery_half(chosen)
                            first_result = stats([float(r["outcome_pips"]) for r in first]) if len(first) >= MIN_HALF_SAMPLES else None
                            second_result = stats([float(r["outcome_pips"]) for r in second]) if len(second) >= MIN_HALF_SAMPLES else None
                            if not first_result or not second_result:
                                continue
                            if float(first_result["expectancy_pips"]) <= 0.0 or float(second_result["expectancy_pips"]) <= 0.0:
                                continue
                            if first_result["profit_factor"] is None or float(first_result["profit_factor"]) <= 1.0:
                                continue
                            if second_result["profit_factor"] is None or float(second_result["profit_factor"]) <= 1.0:
                                continue
                            confirmation_capacity = sum(1 for record in confirmation_records if matches(record, candidate, "confirmation"))
                            if confirmation_capacity < MIN_CONFIRMATION_SAMPLES:
                                continue
                            candidate["discovery"] = discovery
                            candidate["discovery_first_half"] = first_result
                            candidate["discovery_second_half"] = second_result
                            candidate["holdout_structural_n"] = confirmation_capacity
                            candidates.append(candidate)

    candidates.sort(
        key=lambda c: (
            min(float(c["discovery_first_half"]["expectancy_pips"]), float(c["discovery_second_half"]["expectancy_pips"])),
            float(c["discovery"]["expectancy_pips"]),
            float(c["discovery"]["profit_factor"] or -math.inf),
        ),
        reverse=True,
    )
    finalists = candidates[:20]

    results: list[dict[str, Any]] = []
    for candidate in finalists:
        final_confirmation_records: list[Record] = grouped.get(
            (
                str(candidate["pair"]),
                int(candidate["horizon"]),
                str(candidate["regime"]),
                str(candidate["session"]),
                "confirmation",
            ),
            [],
        )
        confirmation = evaluate(final_confirmation_records, candidate, "confirmation")
        if confirmation is None:
            continue
        chosen = [r for r in final_confirmation_records if matches(r, candidate, "confirmation")]
        values = [float(r["outcome_pips"]) for r in chosen]
        confirmation["stress_0_2"] = stressed_stats(values, 0.2)
        confirmation["stress_0_5"] = stressed_stats(values, 0.5)
        confirmation["_values"] = values
        gate = promotion_gate(confirmation)
        confirmation.pop("_values", None)
        results.append({
            "candidate": candidate,
            "confirmation": confirmation,
            "promotion_gate": gate,
            "promotion_eligible": all(gate.values()),
        })

    output = {
        "status": "SURVIVAL_V2_COMPLETED",
        "methodology": {
            "source": "immutable target_records from verified final holdout research",
            "candidate_granularity": "pair-specific, regime-specific, session-specific",
            "discovery_min_samples": MIN_DISCOVERY_SAMPLES,
            "confirmation_min_samples": MIN_CONFIRMATION_SAMPLES,
            "discovery_temporal_gate": "both chronological discovery halves must have positive expectancy and profit factor above 1",
            "selection_data": "discovery only; no confirmation outcome is used to select finalists",
            "confirmation_stress": "additional 0.2 and 0.5 pips per trade beyond embedded BID/ASK costs",
            "promotion_temporal_gate": "at least two confirmation years with >=25 observations and positive expectancy",
            "live_authorization": "never granted by this research job",
        },
        "candidate_pool": len(candidates),
        "finalists": len(results),
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
