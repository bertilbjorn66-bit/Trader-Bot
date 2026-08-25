from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

MIN_KNOWLEDGE_SAMPLES = 30
MIN_STRONG_SAMPLES = 100


@dataclass(frozen=True)
class CellStats:
    n: int
    expectancy_pips: float
    profit_factor: float | None
    win_rate: float
    median_outcome_pips: float
    max_drawdown_pips: float
    positive_years: int
    observed_years: int
    bootstrap_low: float | None
    bootstrap_high: float | None

    @property
    def stability_ratio(self) -> float:
        if self.observed_years == 0:
            return 0.0
        return self.positive_years / self.observed_years

    @property
    def status(self) -> str:
        if self.n < MIN_KNOWLEDGE_SAMPLES:
            return "UNKNOWN"
        if self.expectancy_pips <= 0.0 or self.profit_factor is None or self.profit_factor <= 1.0:
            return "NO_TRADE"
        if self.n >= MIN_STRONG_SAMPLES and (self.bootstrap_low is None or self.bootstrap_low > 0.0) and self.stability_ratio >= 0.67:
            return "STRONG_CONTEXT"
        return "WATCH_CONTEXT"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _bucket_agreement(value: float) -> str:
    if value < 0.50:
        return "<0.50"
    if value < 0.60:
        return "0.50-0.59"
    if value < 0.70:
        return "0.60-0.69"
    if value < 0.80:
        return "0.70-0.79"
    return "0.80+"


def _bucket_distance(value: float) -> str:
    if value <= 0.5:
        return "<=0.50"
    if value <= 1.0:
        return "0.51-1.00"
    if value <= 1.5:
        return "1.01-1.50"
    if value <= 2.0:
        return "1.51-2.00"
    return ">2.00"


def enrich_record(record: dict[str, Any]) -> dict[str, Any]:
    required = (
        "pair",
        "timestamp",
        "horizon",
        "regime",
        "session",
        "direction",
        "agreement",
        "median_distance",
        "outcome_pips",
        "split",
    )
    missing = [key for key in required if key not in record]
    if missing:
        raise ValueError(f"context record missing required fields: {missing}")
    timestamp = datetime.fromisoformat(str(record["timestamp"]))
    if timestamp.tzinfo is None:
        raise ValueError("context record timestamps must be timezone-aware")
    agreement = float(record["agreement"])
    distance = float(record["median_distance"])
    outcome = float(record["outcome_pips"])
    if not math.isfinite(agreement) or not math.isfinite(distance) or not math.isfinite(outcome):
        raise ValueError("context record contains non-finite numeric data")
    enriched = dict(record)
    enriched["year"] = timestamp.year
    enriched["month"] = timestamp.month
    enriched["weekday"] = timestamp.strftime("%A").lower()
    enriched["hour_utc"] = timestamp.hour
    enriched["hour_block_utc"] = f"{timestamp.hour:02d}:00-{(timestamp.hour + 1) % 24:02d}:00"
    enriched["agreement_band"] = _bucket_agreement(agreement)
    enriched["distance_band"] = _bucket_distance(distance)
    enriched["outcome_sign"] = "win" if outcome > 0.0 else "loss" if outcome < 0.0 else "flat"
    return enriched


def _bootstrap_mean(values: list[float], repetitions: int = 500, seed: int = 20260825) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    state = seed & 0xFFFFFFFF
    means: list[float] = []
    for _ in range(repetitions):
        sample: list[float] = []
        for _ in values:
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            sample.append(values[state % len(values)])
        means.append(mean(sample))
    means.sort()
    return means[int(0.025 * repetitions)], means[int(0.975 * repetitions) - 1]


def _stats(records: Iterable[dict[str, Any]]) -> CellStats:
    rows = list(records)
    values = [float(row["outcome_pips"]) for row in rows]
    wins = [value for value in values if value > 0.0]
    losses = [-value for value in values if value < 0.0]
    gross_loss = sum(losses)
    expectancy = mean(values) if values else 0.0
    equity = peak = max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    years: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        years[int(row["year"])].append(float(row["outcome_pips"]))
    positive_years = sum(mean(year_values) > 0.0 for year_values in years.values())
    low, high = _bootstrap_mean(values)
    return CellStats(
        n=len(values),
        expectancy_pips=expectancy,
        profit_factor=sum(wins) / gross_loss if gross_loss else None,
        win_rate=sum(value > 0.0 for value in values) / len(values) if values else 0.0,
        median_outcome_pips=median(values) if values else 0.0,
        max_drawdown_pips=max_drawdown,
        positive_years=positive_years,
        observed_years=len(years),
        bootstrap_low=low,
        bootstrap_high=high,
    )


def _cell_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row["pair"]),
        str(row["horizon"]),
        str(row["regime"]),
        str(row["session"]),
        str(row["weekday"]),
        str(row["agreement_band"]),
        str(row["distance_band"]),
        str(row["direction"]),
        str(row["split"]),
    )


def _serialize_stats(stats: CellStats) -> dict[str, Any]:
    return {
        "n": stats.n,
        "expectancy_pips": stats.expectancy_pips,
        "profit_factor": stats.profit_factor,
        "win_rate": stats.win_rate,
        "median_outcome_pips": stats.median_outcome_pips,
        "max_drawdown_pips": stats.max_drawdown_pips,
        "positive_years": stats.positive_years,
        "observed_years": stats.observed_years,
        "stability_ratio": stats.stability_ratio,
        "bootstrap_expectancy_ci_pips": [stats.bootstrap_low, stats.bootstrap_high],
        "status": stats.status,
    }


def build_atlas(records: list[dict[str, Any]]) -> dict[str, Any]:
    enriched = [enrich_record(record) for record in records]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        groups[_cell_key(row)].append(row)

    cells: list[dict[str, Any]] = []
    for key, rows in sorted(groups.items()):
        stats = _stats(rows)
        cells.append(
            {
                "pair": key[0],
                "horizon": int(key[1]),
                "regime": key[2],
                "session": key[3],
                "weekday": key[4],
                "agreement_band": key[5],
                "distance_band": key[6],
                "direction": key[7],
                "split": key[8],
                "stats": _serialize_stats(stats),
            }
        )

    pair_overview: list[dict[str, Any]] = []
    for pair in sorted({str(row["pair"]) for row in enriched}):
        pair_rows = [row for row in enriched if row["pair"] == pair]
        pair_stats = _stats(pair_rows)
        pair_overview.append({"pair": pair, "stats": _serialize_stats(pair_stats), "record_count": len(pair_rows)})

    strong = [cell for cell in cells if cell["split"] == "confirmation" and cell["stats"]["status"] == "STRONG_CONTEXT"]
    no_trade = [cell for cell in cells if cell["split"] == "confirmation" and cell["stats"]["status"] == "NO_TRADE"]
    watch = [cell for cell in cells if cell["split"] == "confirmation" and cell["stats"]["status"] == "WATCH_CONTEXT"]

    context_coverage = {
        "pairs": sorted({str(row["pair"]) for row in enriched}),
        "horizons": sorted({int(row["horizon"]) for row in enriched}),
        "regimes": sorted({str(row["regime"]) for row in enriched}),
        "sessions": sorted({str(row["session"]) for row in enriched}),
        "weekdays": sorted({str(row["weekday"]) for row in enriched}),
        "agreement_bands": sorted({str(row["agreement_band"]) for row in enriched}),
        "distance_bands": sorted({str(row["distance_band"]) for row in enriched}),
        "directions": sorted({str(row["direction"]) for row in enriched}),
    }

    result = {
        "status": "CONTEXT_ATLAS_COMPLETED",
        "source": "VERIFIED-FINAL-HOLDOUT-RESEARCH",
        "record_count": len(enriched),
        "coverage": context_coverage,
        "pair_overview": pair_overview,
        "cells": cells,
        "confirmation_contexts": {
            "strong_contexts": sorted(strong, key=lambda cell: (cell["stats"]["expectancy_pips"], cell["stats"]["n"]), reverse=True)[:250],
            "watch_contexts": sorted(watch, key=lambda cell: (cell["stats"]["expectancy_pips"], cell["stats"]["n"]), reverse=True)[:250],
            "no_trade_contexts": sorted(no_trade, key=lambda cell: (cell["stats"]["expectancy_pips"], cell["stats"]["n"]))[:250],
        },
        "methodology": {
            "purpose": "map conditional behavior and explicit no-trade regions without changing the validated research gates",
            "context_dimensions": ["pair", "horizon", "regime", "session", "weekday", "agreement", "similarity_distance", "direction"],
            "selection_rule": "no candidate is selected here; this artifact is descriptive intelligence only",
            "strong_context_rule": "confirmation-only, n >= 100, expectancy > 0, profit factor > 1, lower bootstrap expectancy bound > 0, positive expectancy in >= 67% of observed years",
            "no_trade_rule": "confirmation-only, n >= 30, non-positive expectancy or profit factor <= 1",
            "leakage_rule": "input records retain the upstream chronological split; no confirmation result selects or tunes research candidates",
            "input_mutation": "none",
            "live_authorization": "never granted by this analysis",
        },
    }
    result["atlas_fingerprint"] = fingerprint(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deep conditional market-context atlas from the verified holdout artifact.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records = data.get("target_records")
    if not isinstance(records, list) or not records:
        raise SystemExit("input does not contain a non-empty target_records list")
    result = build_atlas(records)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
