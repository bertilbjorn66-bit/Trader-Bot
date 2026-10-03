from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

import numpy as np

from research.datafeed_empirical import PAIR_TO_SYMBOL, _execution_valid_rows, load_feed_bars
from research.non_live_evaluation import block_bootstrap_means, bootstrap_means, profit_factor
from research.statistics import hac_mean_pvalue

PAIR_PIP: dict[str, float] = {
    "EUR/USD": 0.0001,
    "GBP/USD": 0.0001,
    "USD/JPY": 0.01,
    "AUD/USD": 0.0001,
    "USD/CAD": 0.0001,
    "USD/CHF": 0.0001,
    "NZD/USD": 0.0001,
    "EUR/JPY": 0.01,
    "GBP/JPY": 0.01,
}
WEEKDAYS = (0, 1, 2, 3, 4)
QUARTERS = (1, 2, 3, 4)
ORIENTATIONS = ("momentum", "reversion")
HORIZONS = (1, 3, 5)
RETURN_LOOKBACKS = (1,)
FAMILY_SIZE = len(WEEKDAYS) * len(QUARTERS) * len(ORIENTATIONS) * len(HORIZONS)
DISCOVERY_FRACTION = 0.60
MIN_DISCOVERY_SAMPLES = 150
MIN_DISCOVERY_PF = 1.10
MIN_PAIR_SAMPLES = 20
MIN_POSITIVE_PAIRS = 3
MAX_PAIR_CONCENTRATION = 0.80
BOOTSTRAP_REPS = 2000
BLOCK_SIZE = 5
ALPHA = 0.05
STRESS_COSTS_PIPS = (0.5, 1.0, 1.5)
CONTRACT_VERSION = "v1-calendar-seasonality-weekday-quarter-conditioned-direction"


@dataclass(frozen=True)
class DailyBar:
    day: date
    bid_open: float
    ask_open: float
    bid_close: float
    ask_close: float


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else float(str(value))


def _daily_bars(input_dir: Path) -> dict[str, list[DailyBar]]:
    daily: dict[str, list[DailyBar]] = {}
    for pair, symbol in PAIR_TO_SYMBOL.items():
        rows, _quality = _execution_valid_rows(
            load_feed_bars(input_dir / f"{symbol}.jsonl"), pair
        )
        grouped: dict[date, list[Mapping[str, object]]] = defaultdict(list)
        for row in rows:
            timestamp_ms = int(_number(row["timestamp"]))
            day = datetime.fromtimestamp(
                timestamp_ms / 1000, tz=timezone.utc
            ).date()
            grouped[day].append(row)
        complete: list[DailyBar] = []
        for day, day_rows in sorted(grouped.items()):
            day_rows.sort(key=lambda row: int(_number(row["timestamp"])))
            stamps = [int(_number(row["timestamp"])) for row in day_rows]
            if len(day_rows) < 100 or any(
                b - a != 600_000 for a, b in zip(stamps, stamps[1:])
            ):
                continue
            first, last = day_rows[0], day_rows[-1]
            complete.append(
                DailyBar(
                    day=day,
                    bid_open=_number(first["bid_open"]),
                    ask_open=_number(first["ask_open"]),
                    bid_close=_number(last["bid_close"]),
                    ask_close=_number(last["ask_close"]),
                )
            )
        if len(complete) < 1000:
            raise ValueError(f"insufficient complete daily bars for {pair}: {len(complete)}")
        daily[pair] = complete
    return daily


def family_hypotheses() -> list[dict[str, object]]:
    return [
        {
            "weekday": weekday,
            "quarter": quarter,
            "orientation": orientation,
            "horizon": horizon,
        }
        for weekday in WEEKDAYS
        for quarter in QUARTERS
        for orientation in ORIENTATIONS
        for horizon in HORIZONS
    ]


def _common_days(daily: Mapping[str, Sequence[DailyBar]]) -> list[date]:
    return sorted(set.intersection(*(set(bar.day for bar in bars) for bars in daily.values())))


def _previous_return(bars: Sequence[DailyBar], index: int, lookback: int = 1) -> float | None:
    if index < lookback:
        return None
    mids = np.asarray(
        [(bar.bid_close + bar.ask_close) / 2.0 for bar in bars],
        dtype=np.float64,
    )
    base = mids[index - lookback]
    if base <= 0:
        return None
    value = math.log(mids[index] / base)
    return float(value) if math.isfinite(value) else None


def _outcomes(
    candidate: Mapping[str, Any],
    daily: Mapping[str, Sequence[DailyBar]],
    indices: Mapping[str, Mapping[date, int]],
    entry_days: Sequence[date],
    split_cutoff: date,
    holdout: bool,
) -> tuple[list[float], dict[str, list[float]], dict[date, list[float]]]:
    values: list[float] = []
    by_pair: dict[str, list[float]] = defaultdict(list)
    by_timestamp: dict[date, list[float]] = defaultdict(list)
    weekday = int(candidate["weekday"])
    quarter = int(candidate["quarter"])
    orientation = str(candidate["orientation"])
    horizon = int(candidate["horizon"])

    for entry_day in entry_days:
        in_holdout = entry_day >= split_cutoff
        if in_holdout != holdout:
            continue
        if entry_day.weekday() != weekday:
            continue
        if ((entry_day.month - 1) // 3 + 1) != quarter:
            continue

        for pair, bars in daily.items():
            index = indices[pair].get(entry_day)
            if index is None or index + horizon - 1 >= len(bars):
                continue
            signal = _previous_return(bars, index, 1)
            if signal is None or signal == 0.0:
                continue
            direction = 1 if signal > 0 else -1
            if orientation == "reversion":
                direction *= -1
            entry = bars[index]
            target = bars[index + horizon - 1]
            movement = (
                (target.bid_close - entry.ask_open) / PAIR_PIP[pair]
                if direction > 0
                else (entry.bid_open - target.ask_close) / PAIR_PIP[pair]
            )
            value = float(movement)
            values.append(value)
            by_pair[pair].append(value)
            by_timestamp[entry_day].append(value)
    return values, by_pair, by_timestamp


def _bootstrap_lower(timestamp_means: Mapping[date, float], seed: int) -> tuple[float, float]:
    values = list(timestamp_means.values())
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=seed)
    block = block_bootstrap_means(
        values, block_size=min(BLOCK_SIZE, len(values)), reps=BOOTSTRAP_REPS, seed=seed + 1
    )
    return ordinary[49], block[49]


def _evaluate(
    values: Sequence[float],
    by_pair: Mapping[str, Sequence[float]],
    by_timestamp: Mapping[date, Sequence[float]],
    with_bootstrap: bool,
) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "unique_timestamps": 0,
            "expectancy_pips": None,
            "profit_factor": None,
            "hac_one_sided_pvalue": 1.0,
            "ordinary_bootstrap_lower": None,
            "blocked_bootstrap_lower": None,
            "positive_pair_count": 0,
            "largest_pair_observation_share": 1.0,
            "stress": {},
            "passes_pre_holm": False,
        }
    timestamp_means = {day: mean(v) for day, v in by_timestamp.items()}
    expectancy = mean(values)
    pf = profit_factor(list(values))
    positive_pairs = sum(
        1
        for series in by_pair.values()
        if len(series) >= MIN_PAIR_SAMPLES
        and mean(series) > 0.0
        and (pair_pf := profit_factor(list(series))) is not None
        and float(pair_pf) > 1.0
    )
    concentration = max(
        (len(series) / len(values) for series in by_pair.values()),
        default=1.0,
    )
    result: dict[str, Any] = {
        "n": len(values),
        "unique_timestamps": len(timestamp_means),
        "expectancy_pips": expectancy,
        "profit_factor": pf,
        "hac_one_sided_pvalue": (
            1.0
            if len(timestamp_means) < 2
            else hac_mean_pvalue(
                list(timestamp_means.values()),
                max_lag=min(5, len(timestamp_means) - 1),
            )
        ),
        "ordinary_bootstrap_lower": None,
        "blocked_bootstrap_lower": None,
        "positive_pair_count": positive_pairs,
        "largest_pair_observation_share": concentration,
        "stress": {
            str(cost): {
                "expectancy_pips": mean(value - cost for value in values),
                "profit_factor": profit_factor([value - cost for value in values]),
            }
            for cost in STRESS_COSTS_PIPS
        },
        "passes_pre_holm": (
            len(values) >= MIN_DISCOVERY_SAMPLES
            and len(timestamp_means) >= 100
            and expectancy > 0.0
            and pf is not None
            and float(pf) >= MIN_DISCOVERY_PF
            and positive_pairs >= MIN_POSITIVE_PAIRS
            and concentration <= MAX_PAIR_CONCENTRATION
        ),
    }
    if with_bootstrap:
        ordinary_lower, blocked_lower = _bootstrap_lower(timestamp_means, 20261003)
        result["ordinary_bootstrap_lower"] = ordinary_lower
        result["blocked_bootstrap_lower"] = blocked_lower
        result["passes_pre_holm"] = bool(result["passes_pre_holm"]) and ordinary_lower > 0 and blocked_lower > 0
    return result


def _holm(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        results, key=lambda item: float(item["discovery"]["hac_one_sided_pvalue"])
    )
    previous = 0.0
    total = len(ordered)
    for i, item in enumerate(ordered):
        adjusted = min(
            1.0,
            max(
                previous,
                (total - i) * float(item["discovery"]["hac_one_sided_pvalue"]),
            ),
        )
        item["discovery"]["holm_adjusted_pvalue"] = adjusted
        item["discovery"]["passes_familywise"] = (
            bool(item["discovery"]["passes_pre_holm"]) and adjusted <= ALPHA
        )
        previous = adjusted
    return ordered


def run_discovery(feed_dir: Path) -> dict[str, Any]:
    daily = _daily_bars(feed_dir)
    indices: dict[str, dict[date, int]] = {
        pair: {bar.day: i for i, bar in enumerate(bars)}
        for pair, bars in daily.items()
    }
    entry_days = _common_days(daily)
    if len(entry_days) < 500:
        raise ValueError(f"too few common daily entry days: {len(entry_days)}")
    split_cutoff = entry_days[int(len(entry_days) * DISCOVERY_FRACTION)]

    results: list[dict[str, Any]] = []
    for hypothesis in family_hypotheses():
        values, by_pair, by_timestamp = _outcomes(
            hypothesis, daily, indices, entry_days, split_cutoff, False
        )
        results.append(
            {
                **hypothesis,
                "candidate": dict(hypothesis),
                "discovery": _evaluate(values, by_pair, by_timestamp, False),
            }
        )

    for item in results:
        if item["discovery"]["passes_pre_holm"]:
            values, by_pair, by_timestamp = _outcomes(
                item["candidate"], daily, indices, entry_days, split_cutoff, False
            )
            item["discovery"] = _evaluate(values, by_pair, by_timestamp, True)

    ordered = _holm(results)
    survivors = [
        item for item in ordered if item["discovery"].get("passes_familywise")
    ]
    survivors.sort(
        key=lambda item: (
            float(item["discovery"]["holm_adjusted_pvalue"]),
            -float(item["discovery"]["ordinary_bootstrap_lower"] or -math.inf),
            -float(item["discovery"]["expectancy_pips"] or -math.inf),
        )
    )

    confirmation: dict[str, Any] | None = None
    if survivors:
        frozen = survivors[0]
        values, by_pair, by_timestamp = _outcomes(
            frozen["candidate"], daily, indices, entry_days, split_cutoff, True
        )
        confirmation_stats = _evaluate(values, by_pair, by_timestamp, True)
        confirmation_stats["passes_final_confirmation"] = bool(
            confirmation_stats["passes_pre_holm"]
            and float(confirmation_stats["hac_one_sided_pvalue"]) <= ALPHA
        )
        confirmation = {
            "rank": 1,
            "candidate": frozen["candidate"],
            "discovery": frozen["discovery"],
            "confirmation": confirmation_stats,
            "state": "PASS" if confirmation_stats["passes_final_confirmation"] else "FAIL",
        }

    return {
        "status": "CALENDAR_SEASONALITY_DISCOVERY_COMPLETED",
        "contract_version": CONTRACT_VERSION,
        "family_size": FAMILY_SIZE,
        "candidate_count": len(survivors),
        "top_candidates": survivors[:10],
        "confirmation": confirmation,
        "entry_day_count": len(entry_days),
        "global_split_cutoff": split_cutoff.isoformat(),
        "selection_policy": {
            "whole_family_holm": True,
            "holm_scope": FAMILY_SIZE,
            "confirmation_used_for_selection": False,
            "discovery_fraction": DISCOVERY_FRACTION,
            "signal": "prior-complete-day return sign, conditioned on entry weekday and calendar quarter",
            "orientations": list(ORIENTATIONS),
            "horizons": list(HORIZONS),
            "stress_costs_pips": list(STRESS_COSTS_PIPS),
            "pair_gate": ">=3 positive pairs with >=20 observations each and <=80% concentration",
        },
        "source_run_id": 34139659497,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Non-live calendar seasonality research.")
    parser.add_argument("--feed-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_discovery(Path(args.feed_dir))
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"STATUS={report['status']}")
    print(f"FAMILY_SIZE={report['family_size']}")
    print(f"CANDIDATE_COUNT={report['candidate_count']}")
    if report["confirmation"] is None:
        print("CONFIRMATION_STATE=NO_DISCOVERY_CANDIDATE")
    else:
        confirmation = report["confirmation"]["confirmation"]
        print(f"CONFIRMATION_STATE={report['confirmation']['state']}")
        print(f"CONFIRMATION_EXPECTANCY_PIPS={confirmation['expectancy_pips']}")
        print(f"CONFIRMATION_PROFIT_FACTOR={confirmation['profit_factor']}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
