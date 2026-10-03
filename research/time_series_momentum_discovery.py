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
from research.non_live_evaluation import profit_factor
from research.statistics import hac_mean_pvalue

PAIR_PIP: dict[str, float] = {
    "EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01,
    "AUD/USD": 0.0001, "USD/CAD": 0.0001, "USD/CHF": 0.0001,
    "NZD/USD": 0.0001, "EUR/JPY": 0.01, "GBP/JPY": 0.01,
}
LOOKBACKS = (1, 3, 5, 10, 20)
THRESHOLDS = (0.5, 1.0, 1.5, 2.0)
ORIENTATIONS = ("momentum", "reversion")
HORIZONS = (1, 3, 5)
VOL_WINDOW = 20
FAMILY_SIZE = len(LOOKBACKS) * len(THRESHOLDS) * len(ORIENTATIONS) * len(HORIZONS)
MIN_DISCOVERY_SAMPLES = 150
MIN_PAIR_SAMPLES = 20
MIN_POSITIVE_PAIRS = 3
MAX_PAIR_CONCENTRATION = 0.80
MIN_DISCOVERY_PF = 1.10
ALPHA = 0.05
BOOTSTRAP_REPS = 2000
BLOCK_SIZE = 4
STRESS_COSTS_PIPS = (0.5, 1.0, 1.5)
DISCOVERY_FRACTION = 0.60
CONTRACT_VERSION = "v1-volatility-normalized-time-series-momentum-reversal"
SOURCE_RUN_ID = 34139659497

@dataclass(frozen=True)
class DailyBar:
    day: date
    bid_open: float
    ask_open: float
    bid_close: float
    ask_close: float

def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else float(str(value))

def _daily_bars(input_dir: Path) -> tuple[dict[str, list[DailyBar]], dict[str, dict[str, Any]]]:
    daily: dict[str, list[DailyBar]] = {}
    quality: dict[str, dict[str, Any]] = {}
    for pair, symbol in PAIR_TO_SYMBOL.items():
        rows, pair_quality = _execution_valid_rows(load_feed_bars(input_dir / f"{symbol}.jsonl"), pair)
        grouped: dict[date, list[Mapping[str, object]]] = defaultdict(list)
        for row in rows:
            timestamp_ms = int(_number(row["timestamp"]))
            day = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date()
            grouped[day].append(row)
        complete: list[DailyBar] = []
        for day, day_rows in sorted(grouped.items()):
            day_rows.sort(key=lambda row: int(_number(row["timestamp"])))
            stamps = [int(_number(row["timestamp"])) for row in day_rows]
            if len(day_rows) < 100:
                continue
            if any(b - a != 600_000 for a, b in zip(stamps, stamps[1:])):
                continue
            first, last = day_rows[0], day_rows[-1]
            complete.append(DailyBar(
                day=day,
                bid_open=_number(first["bid_open"]),
                ask_open=_number(first["ask_open"]),
                bid_close=_number(last["bid_close"]),
                ask_close=_number(last["ask_close"]),
            ))
        if len(complete) < 1000:
            raise ValueError(f"insufficient complete daily bars for {pair}: {len(complete)}")
        daily[pair] = complete
        quality[pair] = {**pair_quality, "complete_daily_bar_count": len(complete)}
    return daily, quality

def family_hypotheses() -> list[dict[str, object]]:
    return [
        {"lookback": lookback, "threshold": threshold, "orientation": orientation, "horizon": horizon}
        for lookback in LOOKBACKS
        for threshold in THRESHOLDS
        for orientation in ORIENTATIONS
        for horizon in HORIZONS
    ]

def _common_days(daily: Mapping[str, Sequence[DailyBar]]) -> list[date]:
    return sorted(set.intersection(*(set(bar.day for bar in bars) for bars in daily.values())))

def _score(bars: Sequence[DailyBar], index: int, lookback: int) -> float | None:
    if index < lookback or index < VOL_WINDOW:
        return None
    mids = np.asarray([(bar.bid_close + bar.ask_close) / 2.0 for bar in bars], dtype=np.float64)
    base = mids[index - lookback]
    if base <= 0:
        return None
    cumulative = math.log(mids[index] / base)
    returns = np.diff(np.log(mids[index - VOL_WINDOW : index + 1]))
    if len(returns) < 2:
        return None
    vol = float(np.std(returns, ddof=1))
    denom = vol * math.sqrt(lookback)
    if not math.isfinite(denom) or denom <= 0:
        return None
    score = cumulative / denom
    return score if math.isfinite(score) else None

def _outcomes(
    candidate: Mapping[str, Any],
    daily: Mapping[str, Sequence[DailyBar]],
    indices: Mapping[str, Mapping[date, int]],
    entry_days: Sequence[date],
    split_cutoff: date | None,
    holdout: bool,
) -> tuple[list[float], dict[str, list[float]], dict[date, list[float]]]:
    values: list[float] = []
    by_pair: dict[str, list[float]] = defaultdict(list)
    by_timestamp: dict[date, list[float]] = defaultdict(list)
    if split_cutoff is None:
        return values, by_pair, by_timestamp
    lookback = int(candidate["lookback"])
    threshold = float(candidate["threshold"])
    orientation = str(candidate["orientation"])
    horizon = int(candidate["horizon"])
    for entry_day in entry_days:
        is_holdout = entry_day >= split_cutoff
        if is_holdout != holdout:
            continue
        for pair, bars in daily.items():
            index = indices[pair].get(entry_day)
            if index is None:
                continue
            signal_index = index - 1
            score = _score(bars, signal_index, lookback) if signal_index >= 0 else None
            if score is None or abs(score) < threshold:
                continue
            if index + horizon - 1 >= len(bars):
                continue
            entry = bars[index]
            target = bars[index + horizon - 1]
            direction = 1 if score > 0 else -1
            if orientation == "reversion":
                direction *= -1
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

def _bootstrap_lower(values: Sequence[float], seed: int) -> float:
    if len(values) < 2:
        return math.nan
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=np.float64)
    means = np.mean(rng.choice(array, size=(BOOTSTRAP_REPS, len(array)), replace=True), axis=1)
    return float(np.quantile(means, 0.025))

def _block_lower(timestamp_means: Mapping[date, float], seed: int) -> float:
    ordered = sorted(timestamp_means)
    if len(ordered) < 2:
        return math.nan
    blocks = [ordered[i:i + BLOCK_SIZE] for i in range(0, len(ordered), BLOCK_SIZE)]
    rng = np.random.default_rng(seed)
    means: list[float] = []
    for _ in range(BOOTSTRAP_REPS):
        selected: list[date] = []
        while len(selected) < len(ordered):
            selected.extend(blocks[int(rng.integers(0, len(blocks)))])
        means.append(mean(timestamp_means[d] for d in selected[:len(ordered)]))
    return float(np.quantile(np.asarray(means, dtype=np.float64), 0.025))

def _evaluate(
    values: Sequence[float],
    by_pair: Mapping[str, Sequence[float]],
    by_timestamp: Mapping[date, Sequence[float]],
    with_bootstrap: bool,
) -> dict[str, Any]:
    if not values:
        return {
            "n": 0, "unique_timestamps": 0, "expectancy_pips": None, "profit_factor": None,
            "hac_one_sided_pvalue": 1.0, "ordinary_bootstrap_lower": math.nan,
            "blocked_bootstrap_lower": math.nan, "positive_pair_count": 0,
            "largest_pair_observation_share": 1.0, "stress": {}, "passes_pre_holm": False,
        }
    timestamp_means = {d: mean(v) for d, v in by_timestamp.items()}
    expectancy = mean(values)
    pf = profit_factor(list(values))
    positive_pairs = sum(
        1 for v in by_pair.values()
        if len(v) >= MIN_PAIR_SAMPLES and mean(v) > 0
        and (pair_pf := profit_factor(list(v))) is not None and float(pair_pf) > 1.0
    )
    concentration = max((len(v) / len(values) for v in by_pair.values()), default=1.0)
    result: dict[str, Any] = {
        "n": len(values), "unique_timestamps": len(timestamp_means),
        "expectancy_pips": expectancy, "profit_factor": pf,
        "hac_one_sided_pvalue": (
            1.0 if len(timestamp_means) < 2 else hac_mean_pvalue(
                list(timestamp_means.values()), max_lag=min(5, len(timestamp_means) - 1)
            )
        ),
        "ordinary_bootstrap_lower": math.nan, "blocked_bootstrap_lower": math.nan,
        "positive_pair_count": positive_pairs, "largest_pair_observation_share": concentration,
        "stress": {
            str(cost): {"expectancy_pips": mean(x - cost for x in values), "profit_factor": profit_factor([x - cost for x in values])}
            for cost in STRESS_COSTS_PIPS
        },
        "passes_pre_holm": (
            len(values) >= MIN_DISCOVERY_SAMPLES and len(timestamp_means) >= 100
            and expectancy > 0 and pf is not None and float(pf) >= MIN_DISCOVERY_PF
            and positive_pairs >= MIN_POSITIVE_PAIRS and concentration <= MAX_PAIR_CONCENTRATION
        ),
    }
    if with_bootstrap:
        result["ordinary_bootstrap_lower"] = _bootstrap_lower(list(timestamp_means.values()), 20261003)
        result["blocked_bootstrap_lower"] = _block_lower(timestamp_means, 20261004)
        result["passes_pre_holm"] = bool(result["passes_pre_holm"]) and float(result["ordinary_bootstrap_lower"]) > 0 and float(result["blocked_bootstrap_lower"]) > 0
    return result

def _holm(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(results, key=lambda item: float(item["discovery"]["hac_one_sided_pvalue"]))
    previous = 0.0
    total = len(ordered)
    for i, item in enumerate(ordered):
        adjusted = min(1.0, max(previous, (total - i) * float(item["discovery"]["hac_one_sided_pvalue"])))
        item["discovery"]["holm_adjusted_pvalue"] = adjusted
        item["discovery"]["passes_familywise"] = bool(item["discovery"]["passes_pre_holm"]) and adjusted <= ALPHA
        previous = adjusted
    return ordered

def run_discovery(feed_dir: Path) -> dict[str, Any]:
    daily, feed_quality = _daily_bars(feed_dir)
    indices: dict[str, dict[date, int]] = {
        pair: {bar.day: i for i, bar in enumerate(bars)} for pair, bars in daily.items()
    }
    common_days = _common_days(daily)
    minimum_index = VOL_WINDOW + max(LOOKBACKS) + 1
    entry_days = [day for day in common_days if all(indices[pair].get(day, 0) >= minimum_index for pair in daily)]
    if len(entry_days) < 300:
        raise ValueError(f"too few common entry days: {len(entry_days)}")
    split_cutoff = entry_days[int(len(entry_days) * DISCOVERY_FRACTION)]
    results: list[dict[str, Any]] = []
    for hypothesis in family_hypotheses():
        vals, by_pair, by_ts = _outcomes(hypothesis, daily, indices, entry_days, split_cutoff, False)
        results.append({"candidate": dict(hypothesis), "discovery": _evaluate(vals, by_pair, by_ts, False), **hypothesis})
    for item in results:
        if item["discovery"]["passes_pre_holm"]:
            vals, by_pair, by_ts = _outcomes(item["candidate"], daily, indices, entry_days, split_cutoff, False)
            item["discovery"] = _evaluate(vals, by_pair, by_ts, True)
    ordered = _holm(results)
    survivors = [item for item in ordered if item["discovery"].get("passes_familywise")]
    survivors.sort(key=lambda item: (float(item["discovery"]["holm_adjusted_pvalue"]), -float(item["discovery"]["ordinary_bootstrap_lower"]), -float(item["discovery"]["expectancy_pips"])))
    confirmation: dict[str, Any] | None = None
    if survivors:
        frozen = survivors[0]
        vals, by_pair, by_ts = _outcomes(frozen["candidate"], daily, indices, entry_days, split_cutoff, True)
        conf = _evaluate(vals, by_pair, by_ts, True)
        conf["passes_final_confirmation"] = bool(conf["passes_pre_holm"]) and float(conf["hac_one_sided_pvalue"]) <= ALPHA
        confirmation = {"rank": 1, "candidate": frozen["candidate"], "discovery": frozen["discovery"], "confirmation": conf, "state": "PASS" if conf["passes_final_confirmation"] else "FAIL"}
    return {
        "status": "TIME_SERIES_MOMENTUM_DISCOVERY_COMPLETED",
        "contract_version": CONTRACT_VERSION, "family_size": FAMILY_SIZE,
        "candidate_count": len(survivors), "top_candidates": survivors[:10],
        "confirmation": confirmation, "entry_day_count": len(entry_days),
        "global_split_cutoff": split_cutoff.isoformat(),
        "signal_definition": {
            "score": "prior-day cumulative log return / trailing 20-day return volatility * sqrt(lookback)",
            "entry": "next complete UTC day BID/ASK open",
            "exit": "horizon-day BID/ASK close",
            "lookbacks": list(LOOKBACKS), "thresholds": list(THRESHOLDS),
            "orientations": list(ORIENTATIONS), "horizons": list(HORIZONS),
        },
        "selection_policy": {
            "whole_family_holm": True, "holm_scope": FAMILY_SIZE,
            "confirmation_used_for_selection": False,
            "minimum_discovery_samples": MIN_DISCOVERY_SAMPLES,
            "minimum_discovery_profit_factor": MIN_DISCOVERY_PF,
            "minimum_positive_pairs": MIN_POSITIVE_PAIRS,
            "max_pair_concentration": MAX_PAIR_CONCENTRATION,
            "stress_costs_pips": list(STRESS_COSTS_PIPS),
        },
        "feed_quality": feed_quality, "source_run_id": SOURCE_RUN_ID,
        "promotion_authorized": False, "live_execution_authorized": False,
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Non-live volatility-normalized time-series momentum/reversal research.")
    parser.add_argument("--feed-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_discovery(Path(args.feed_dir))
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"STATUS={report['status']}")
    print(f"FAMILY_SIZE={report['family_size']}")
    print(f"CANDIDATE_COUNT={report['candidate_count']}")
    if report["confirmation"] is None:
        print("CONFIRMATION_STATE=NO_DISCOVERY_CANDIDATE")
    else:
        c = report["confirmation"]["confirmation"]
        print(f"CONFIRMATION_STATE={report['confirmation']['state']}")
        print(f"CONFIRMATION_EXPECTANCY_PIPS={c['expectancy_pips']}")
        print(f"CONFIRMATION_PROFIT_FACTOR={c['profit_factor']}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")

if __name__ == "__main__":
    main()
