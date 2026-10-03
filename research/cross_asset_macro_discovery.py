from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

import numpy as np

from research.datafeed_empirical import (
    PAIR_TO_SYMBOL,
    _execution_valid_rows,
    load_feed_bars,
)
from research.non_live_evaluation import (
    block_bootstrap_means,
    bootstrap_means,
    profit_factor,
)
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
MACRO_FACTORS = ("VIXCLS", "SP500", "DCOILWTICO")
MACRO_LOOKBACKS = (1, 5, 20)
MACRO_THRESHOLDS = (0.5, 1.0, 1.5)
MACRO_STATES = ("high", "low")
ORIENTATIONS = ("momentum", "reversion")
HORIZONS = (1, 3, 5)
FAMILY_SIZE = (
    len(MACRO_FACTORS)
    * len(MACRO_LOOKBACKS)
    * len(MACRO_THRESHOLDS)
    * len(MACRO_STATES)
    * len(ORIENTATIONS)
    * len(HORIZONS)
)
DISCOVERY_FRACTION = 0.60
MIN_DISCOVERY_SAMPLES = 200
MIN_DISCOVERY_PF = 1.10
MIN_PAIR_SAMPLES = 20
MIN_POSITIVE_PAIRS = 3
MAX_PAIR_CONCENTRATION = 0.80
BOOTSTRAP_REPS = 2000
BLOCK_SIZE = 5
ALPHA = 0.05
STRESS_COSTS_PIPS = (0.5, 1.0, 1.5)
CONTRACT_VERSION = "v1-cross-asset-macro-context"
FRED_SOURCE_URLS = {
    "VIXCLS": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
    "SP500": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500",
    "DCOILWTICO": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO",
}


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
                timestamp_ms / 1000.0, tz=timezone.utc
            ).date()
            grouped[day].append(row)

        bars: list[DailyBar] = []
        for day, day_rows in sorted(grouped.items()):
            day_rows.sort(key=lambda row: int(_number(row["timestamp"])))
            stamps = [int(_number(row["timestamp"])) for row in day_rows]
            if len(day_rows) < 100 or any(
                b - a != 600_000 for a, b in zip(stamps, stamps[1:])
            ):
                continue
            first, last = day_rows[0], day_rows[-1]
            bars.append(
                DailyBar(
                    day=day,
                    bid_open=_number(first["bid_open"]),
                    ask_open=_number(first["ask_open"]),
                    bid_close=_number(last["bid_close"]),
                    ask_close=_number(last["ask_close"]),
                )
            )
        if len(bars) < 1000:
            raise ValueError(f"insufficient complete daily bars for {pair}: {len(bars)}")
        daily[pair] = bars
    return daily


def _load_macro_csv(path: Path) -> dict[date, float]:
    values: dict[date, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "DATE" not in reader.fieldnames:
            raise ValueError(f"macro CSV missing DATE column: {path.name}")
        value_column = next(
            (name for name in reader.fieldnames if name != "DATE"),
            None,
        )
        if value_column is None:
            raise ValueError(f"macro CSV missing value column: {path.name}")
        for row in reader:
            raw_date = (row.get("DATE") or "").strip()
            raw_value = (row.get(value_column) or "").strip()
            if not raw_date or not raw_value or raw_value == ".":
                continue
            try:
                values[date.fromisoformat(raw_date)] = float(raw_value)
            except ValueError:
                continue
    if len(values) < 500:
        raise ValueError(f"insufficient macro observations in {path.name}: {len(values)}")
    return values


def family_hypotheses() -> list[dict[str, object]]:
    return [
        {
            "macro_factor": factor,
            "macro_lookback": lookback,
            "macro_threshold": threshold,
            "macro_state": state,
            "orientation": orientation,
            "horizon": horizon,
        }
        for factor in MACRO_FACTORS
        for lookback in MACRO_LOOKBACKS
        for threshold in MACRO_THRESHOLDS
        for state in MACRO_STATES
        for orientation in ORIENTATIONS
        for horizon in HORIZONS
    ]


def _common_days(daily: Mapping[str, Sequence[DailyBar]]) -> list[date]:
    return sorted(
        set.intersection(*(set(bar.day for bar in bars) for bars in daily.values()))
    )


def _macro_score_panel(
    series: Mapping[str, Mapping[date, float]],
) -> dict[str, dict[int, dict[date, float]]]:
    panel: dict[str, dict[int, dict[date, float]]] = {}
    for factor, values in series.items():
        dates = sorted(values)
        raw = np.asarray([values[day] for day in dates], dtype=np.float64)
        factor_panel: dict[int, dict[date, float]] = {}
        for lookback in MACRO_LOOKBACKS:
            score_values: dict[date, float] = {}
            log_values = np.log(raw)
            returns = np.full(len(raw), np.nan, dtype=np.float64)
            if np.all(raw > 0):
                returns[lookback:] = log_values[lookback:] - log_values[:-lookback]
            else:
                returns[lookback:] = (raw[lookback:] - raw[:-lookback]) / np.maximum(
                    np.abs(raw[:-lookback]), 1e-12
                )
            trailing = max(60, lookback * 10)
            for index in range(trailing, len(raw)):
                history = returns[index - trailing:index]
                history = history[np.isfinite(history)]
                if len(history) < max(20, trailing // 2):
                    continue
                centre = float(np.mean(history))
                std = float(np.std(history, ddof=1))
                if not math.isfinite(std) or std <= 0:
                    continue
                score = float((returns[index] - centre) / std)
                if math.isfinite(score):
                    score_values[dates[index]] = score
            factor_panel[lookback] = score_values
        panel[factor] = factor_panel
    return panel


def _previous_return(
    bars: Sequence[DailyBar],
    index: int,
) -> float | None:
    if index < 1:
        return None
    previous = (bars[index - 1].bid_close + bars[index - 1].ask_close) / 2.0
    prior = (
        (bars[index - 2].bid_close + bars[index - 2].ask_close) / 2.0
        if index >= 2
        else previous
    )
    if prior <= 0:
        return None
    value = math.log(previous / prior)
    return value if math.isfinite(value) else None


def _last_available(
    panel: Mapping[date, float],
    target_day: date,
) -> tuple[date, float] | None:
    available = [day for day in panel if day <= target_day]
    if not available:
        return None
    day = max(available)
    return day, float(panel[day])


def _outcomes(
    candidate: Mapping[str, Any],
    daily: Mapping[str, Sequence[DailyBar]],
    indices: Mapping[str, Mapping[date, int]],
    macro_panel: Mapping[str, Mapping[int, Mapping[date, float]]],
    entry_days: Sequence[date],
    split_cutoff: date,
    holdout: bool,
) -> tuple[list[float], dict[str, list[float]], dict[date, list[float]]]:
    values: list[float] = []
    by_pair: dict[str, list[float]] = defaultdict(list)
    by_timestamp: dict[date, list[float]] = defaultdict(list)

    factor = str(candidate["macro_factor"])
    lookback = int(candidate["macro_lookback"])
    threshold = float(candidate["macro_threshold"])
    macro_state = str(candidate["macro_state"])
    orientation = str(candidate["orientation"])
    horizon = int(candidate["horizon"])

    factor_panel = macro_panel[factor][lookback]
    for entry_day in entry_days:
        if (entry_day >= split_cutoff) != holdout:
            continue

        macro_observation = _last_available(
            factor_panel,
            entry_day - timedelta(days=1),
        )
        if macro_observation is None:
            continue
        _macro_day, macro_score = macro_observation
        if macro_state == "high":
            if macro_score < threshold:
                continue
        elif macro_score > -threshold:
            continue

        for pair, bars in daily.items():
            index = indices[pair].get(entry_day)
            if index is None or index < 2 or index + horizon - 1 >= len(bars):
                continue
            signal = _previous_return(bars, index)
            if signal is None or signal == 0.0:
                continue
            direction = 1 if signal > 0.0 else -1
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

    timestamp_means = {day: mean(items) for day, items in by_timestamp.items()}
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
        timestamp_values = list(timestamp_means.values())
        ordinary = bootstrap_means(
            timestamp_values, reps=BOOTSTRAP_REPS, seed=20261003
        )
        blocked = block_bootstrap_means(
            timestamp_values,
            block_size=min(BLOCK_SIZE, len(timestamp_values)),
            reps=BOOTSTRAP_REPS,
            seed=20261004,
        )
        result["ordinary_bootstrap_lower"] = ordinary[49]
        result["blocked_bootstrap_lower"] = blocked[49]
        result["passes_pre_holm"] = (
            bool(result["passes_pre_holm"])
            and float(result["ordinary_bootstrap_lower"]) > 0.0
            and float(result["blocked_bootstrap_lower"]) > 0.0
        )
    return result


def _holm(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        results,
        key=lambda item: float(item["discovery"]["hac_one_sided_pvalue"]),
    )
    previous = 0.0
    total = len(ordered)
    for i, item in enumerate(ordered):
        adjusted = min(
            1.0,
            max(
                previous,
                (total - i)
                * float(item["discovery"]["hac_one_sided_pvalue"]),
            ),
        )
        item["discovery"]["holm_adjusted_pvalue"] = adjusted
        item["discovery"]["passes_familywise"] = (
            bool(item["discovery"]["passes_pre_holm"]) and adjusted <= ALPHA
        )
        previous = adjusted
    return ordered


def run_discovery(
    feed_dir: Path,
    macro_dir: Path,
) -> dict[str, Any]:
    daily = _daily_bars(feed_dir)
    macro_series = {
        factor: _load_macro_csv(macro_dir / f"{factor}.csv")
        for factor in MACRO_FACTORS
    }
    macro_panel = _macro_score_panel(macro_series)
    indices = {
        pair: {bar.day: index for index, bar in enumerate(bars)}
        for pair, bars in daily.items()
    }
    entry_days = _common_days(daily)
    start = max(min(macro_series[factor]) for factor in MACRO_FACTORS)
    entry_days = [
        day
        for day in entry_days
        if day >= start + timedelta(days=30)
    ]
    if len(entry_days) < 500:
        raise ValueError(f"too few common entry days after macro alignment: {len(entry_days)}")
    split_cutoff = entry_days[int(len(entry_days) * DISCOVERY_FRACTION)]

    results: list[dict[str, Any]] = []
    for hypothesis in family_hypotheses():
        values, by_pair, by_timestamp = _outcomes(
            hypothesis,
            daily,
            indices,
            macro_panel,
            entry_days,
            split_cutoff,
            False,
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
                item["candidate"],
                daily,
                indices,
                macro_panel,
                entry_days,
                split_cutoff,
                False,
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
            frozen["candidate"],
            daily,
            indices,
            macro_panel,
            entry_days,
            split_cutoff,
            True,
        )
        stats = _evaluate(values, by_pair, by_timestamp, True)
        stats["passes_final_confirmation"] = bool(
            stats["passes_pre_holm"]
            and float(stats["hac_one_sided_pvalue"]) <= ALPHA
        )
        confirmation = {
            "rank": 1,
            "candidate": frozen["candidate"],
            "discovery": frozen["discovery"],
            "confirmation": stats,
            "state": "PASS" if stats["passes_final_confirmation"] else "FAIL",
        }

    return {
        "status": "CROSS_ASSET_MACRO_DISCOVERY_COMPLETED",
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
            "macro_factors": list(MACRO_FACTORS),
            "lookbacks": list(MACRO_LOOKBACKS),
            "thresholds": list(MACRO_THRESHOLDS),
            "states": list(MACRO_STATES),
            "orientations": list(ORIENTATIONS),
            "horizons": list(HORIZONS),
            "macro_data_contract": "use only the latest FRED observation dated on or before entry_day minus one calendar day",
            "fred_sources": FRED_SOURCE_URLS,
            "price_signal_contract": "prior complete FX day midpoint-return sign; entry next complete UTC day BID/ASK open",
            "stress_costs_pips": list(STRESS_COSTS_PIPS),
            "pair_gate": ">=3 positive pairs with >=20 observations each and <=80% concentration",
        },
        "source_run_id": 34139659497,
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Non-live cross-asset macro context research.")
    parser.add_argument("--feed-dir", required=True)
    parser.add_argument("--macro-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_discovery(Path(args.feed_dir), Path(args.macro_dir))
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"STATUS={report['status']}")
    print(f"FAMILY_SIZE={report['family_size']}")
    print(f"CANDIDATE_COUNT={report['candidate_count']}")
    print(f"ENTRY_DAY_COUNT={report['entry_day_count']}")
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
