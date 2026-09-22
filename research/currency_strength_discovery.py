from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from research.datafeed_empirical import (
    PAIR_TO_SYMBOL,
    _execution_valid_rows,
    load_feed_bars,
)
from research.non_live_evaluation import bootstrap_means, profit_factor
from research.statistics import hac_mean_pvalue


PAIR_CURRENCY = {
    "EUR/USD": ("EUR", "USD"),
    "GBP/USD": ("GBP", "USD"),
    "USD/JPY": ("USD", "JPY"),
    "AUD/USD": ("AUD", "USD"),
    "USD/CAD": ("USD", "CAD"),
    "USD/CHF": ("USD", "CHF"),
    "NZD/USD": ("NZD", "USD"),
    "EUR/JPY": ("EUR", "JPY"),
    "GBP/JPY": ("GBP", "JPY"),
}

PAIR_PIP = {
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

LOOKBACKS = (6, 12, 24, 48)
HORIZONS = (3, 6, 12)
THRESHOLDS = (0.5, 1.0, 1.5)
MODES = ("raw_strength", "volatility_normalized")
ORIENTATIONS = ("momentum", "reversion")

EXPECTED_INTERVAL = timedelta(minutes=10)
ROLLING_VOL_BARS = 48
MIN_DISCOVERY_TRADES = 150
MIN_TIMESTAMP_OBS = 100
MIN_PAIR_TRADES = 20
MIN_POSITIVE_PAIRS = 3
MAX_PAIR_CONCENTRATION = 0.80
MIN_EXPECTANCY_PIPS = 0.0
MIN_PROFIT_FACTOR = 1.10
BOOTSTRAP_REPS = 2000
BOOTSTRAP_BLOCK_SIZE = 6
BOOTSTRAP_LOWER_INDEX = 49
BOOTSTRAP_UPPER_INDEX = -50
FAMILY_ALPHA = 0.05
DISCOVERY_FRACTION = 0.60
DISCOVERY_COST_PIPS = 0.0
STRESS_COSTS_PIPS = (0.5, 1.0, 1.5)

CONTRACT_VERSION = "v1-currency-strength-familywise"


@dataclass(frozen=True)
class Feed:
    pair: str
    timestamps: np.ndarray
    bid_close: np.ndarray
    ask_close: np.ndarray
    mid_close: np.ndarray
    rolling_vol: np.ndarray
    timestamp_index: dict[int, int]
    quality: Mapping[str, object]


@dataclass(frozen=True)
class Trade:
    timestamp_ms: int
    target_end_ms: int
    pair: str
    lookback: int
    horizon: int
    mode: str
    orientation: str
    threshold: float
    signal: float
    outcome_pips: float
    split: str = ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contiguous(timestamps: np.ndarray, start: int, end: int) -> bool:
    if start < 0 or end >= len(timestamps) or start > end:
        return False
    expected_ms = 600_000
    if end - start <= 0:
        return True
    return bool(np.all(np.diff(timestamps[start : end + 1]) == expected_ms))


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    result = np.full(values.shape, np.nan, dtype=np.float64)
    if len(values) < window:
        return result
    valid = np.isfinite(values).astype(np.int64)
    safe = np.nan_to_num(values, nan=0.0)
    cs = np.concatenate(([0.0], np.cumsum(safe)))
    cs2 = np.concatenate(([0.0], np.cumsum(safe * safe)))
    cv = np.concatenate(([0], np.cumsum(valid)))
    count = cv[window:] - cv[:-window]
    total = cs[window:] - cs[:-window]
    total_sq = cs2[window:] - cs2[:-window]
    variance = (
        total_sq
        - np.where(count > 0, total * total / np.maximum(count, 1), 0.0)
    ) / np.maximum(count - 1, 1)
    valid_windows = count == window
    result[window - 1 :] = np.where(
        valid_windows,
        np.sqrt(np.maximum(variance, 0.0)),
        np.nan,
    )
    return result


def load_feeds(input_dir: Path) -> tuple[dict[str, Feed], dict[str, dict[str, object]]]:
    feeds: dict[str, Feed] = {}
    manifest: dict[str, dict[str, object]] = {}
    for pair, symbol in PAIR_TO_SYMBOL.items():
        path = input_dir / f"{symbol}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"missing verified feed for {pair}: {path}")
        rows = load_feed_bars(path)
        valid_rows, quality = _execution_valid_rows(rows, pair)
        if len(valid_rows) < 1000:
            raise ValueError(f"insufficient valid rows for {pair}: {len(valid_rows)}")
        timestamps = np.asarray([int(row["timestamp"]) for row in valid_rows], dtype=np.int64)
        bid_close = np.asarray([float(row["bid_close"]) for row in valid_rows], dtype=np.float64)
        ask_close = np.asarray([float(row["ask_close"]) for row in valid_rows], dtype=np.float64)
        mid_close = (bid_close + ask_close) / 2.0
        one_bar = np.full_like(mid_close, np.nan)
        one_bar[1:] = np.log(mid_close[1:] / mid_close[:-1])
        rolling_vol = _rolling_std(one_bar, ROLLING_VOL_BARS)
        feeds[pair] = Feed(
            pair=pair,
            timestamps=timestamps,
            bid_close=bid_close,
            ask_close=ask_close,
            mid_close=mid_close,
            rolling_vol=rolling_vol,
            timestamp_index={int(value): index for index, value in enumerate(timestamps)},
            quality=quality,
        )
        manifest[pair] = {
            "path": str(path),
            "sha256": _sha256(path),
            "valid_rows": len(valid_rows),
            **quality,
        }
    return feeds, manifest


def _currency_components(
    feeds: Mapping[str, Feed],
    timestamp_ms: int,
    lookback: int,
) -> tuple[dict[str, float], dict[str, float], float]:
    raw: dict[str, list[float]] = defaultdict(list)
    normalized: dict[str, list[float]] = defaultdict(list)
    absolute_returns: list[float] = []

    lag_ms = lookback * 600_000
    for pair, (base, quote) in PAIR_CURRENCY.items():
        feed = feeds[pair]
        end_index = feed.timestamp_index.get(timestamp_ms)
        start_index = feed.timestamp_index.get(timestamp_ms - lag_ms)
        if end_index is None or start_index is None:
            continue
        if not _contiguous(feed.timestamps, start_index, end_index):
            continue
        ret = math.log(feed.mid_close[end_index] / feed.mid_close[start_index])
        if not math.isfinite(ret):
            continue
        raw[base].append(ret)
        raw[quote].append(-ret)
        absolute_returns.append(abs(ret))
        vol = float(feed.rolling_vol[end_index])
        if math.isfinite(vol) and vol > 0.0:
            normalized_return = ret / vol
            normalized[base].append(normalized_return)
            normalized[quote].append(-normalized_return)

    raw_strength = {
        currency: mean(values)
        for currency, values in raw.items()
        if values
    }
    normalized_strength = {
        currency: mean(values)
        for currency, values in normalized.items()
        if values
    }
    dispersion = float(np.median(np.asarray(absolute_returns, dtype=np.float64))) if absolute_returns else math.nan
    return raw_strength, normalized_strength, dispersion


def build_signal_index(
    feeds: Mapping[str, Feed],
    timestamps: Iterable[int],
) -> dict[tuple[int, int, str, str], float]:
    result: dict[tuple[int, int, str, str], float] = {}
    unique_timestamps = sorted(set(timestamps))
    for timestamp_ms in unique_timestamps:
        for lookback in LOOKBACKS:
            raw, normalized, dispersion = _currency_components(
                feeds,
                timestamp_ms,
                lookback,
            )
            for pair, (base, quote) in PAIR_CURRENCY.items():
                raw_score = raw.get(base, math.nan) - raw.get(quote, math.nan)
                norm_score = normalized.get(base, math.nan) - normalized.get(quote, math.nan)
                if math.isfinite(raw_score) and math.isfinite(dispersion) and dispersion > 0.0:
                    result[(timestamp_ms, lookback, pair, "raw_strength")] = raw_score / dispersion
                if math.isfinite(norm_score):
                    result[(timestamp_ms, lookback, pair, "volatility_normalized")] = norm_score
    return result


def _trade_for_signal(
    feed: Feed,
    position: int,
    horizon: int,
    mode: str,
    orientation: str,
    threshold: float,
    signal: float,
    lookback: int,
) -> Trade | None:
    timestamp_ms = int(feed.timestamps[position])
    end_position = position + horizon
    if end_position >= len(feed.timestamps):
        return None
    if not _contiguous(feed.timestamps, position, end_position):
        return None
    direction = 1 if signal > 0.0 else -1
    if orientation == "reversion":
        direction *= -1
    if abs(signal) < threshold:
        return None
    if direction > 0:
        movement = (feed.bid_close[end_position] - feed.ask_close[position]) / PAIR_PIP[feed.pair]
    else:
        movement = (feed.bid_close[position] - feed.ask_close[end_position]) / PAIR_PIP[feed.pair]
    return Trade(
        timestamp_ms=timestamp_ms,
        target_end_ms=int(feed.timestamps[end_position]),
        pair=feed.pair,
        lookback=lookback,
        horizon=horizon,
        mode=mode,
        orientation=orientation,
        threshold=threshold,
        signal=signal,
        outcome_pips=float(movement),
    )


def assign_global_split(trades: list[Trade]) -> tuple[list[Trade], int | None]:
    if not trades:
        return trades, None
    cutoff = sorted({trade.target_end_ms for trade in trades})[
        int(len(set(trade.target_end_ms for trade in trades)) * DISCOVERY_FRACTION)
    ]
    result: list[Trade] = []
    for trade in trades:
        split = "discovery" if trade.target_end_ms < cutoff else "confirmation"
        result.append(
            Trade(
                **{**trade.__dict__, "split": split}
            )
        )
    return result, cutoff


def family_hypotheses() -> list[dict[str, Any]]:
    return [
        {
            "lookback": lookback,
            "horizon": horizon,
            "mode": mode,
            "orientation": orientation,
            "threshold": threshold,
        }
        for lookback in LOOKBACKS
        for horizon in HORIZONS
        for mode in MODES
        for orientation in ORIENTATIONS
        for threshold in THRESHOLDS
    ]


def _pf(values: Sequence[float]) -> float | None:
    return profit_factor(values)


def _clustered_block_lower(
    timestamp_values: Mapping[int, Sequence[float]],
    reps: int,
    seed: int,
) -> float:
    if len(timestamp_values) < 2:
        return math.nan
    ordered = sorted(timestamp_values)
    blocks = [
        ordered[index : index + BOOTSTRAP_BLOCK_SIZE]
        for index in range(0, len(ordered), BOOTSTRAP_BLOCK_SIZE)
    ]
    rng = np.random.default_rng(seed)
    means: list[float] = []
    sample_size = len(ordered)
    for _ in range(reps):
        sampled: list[float] = []
        while len(sampled) < sample_size:
            block = blocks[int(rng.integers(0, len(blocks)))]
            sampled.extend(block)
        values = [
            value
            for timestamp in sampled[:sample_size]
            for value in timestamp_values[timestamp]
        ]
        means.append(mean(values))
    return float(np.quantile(np.asarray(means), 0.025))


def _candidate_metrics(
    feeds: Mapping[str, Feed],
    target_positions: Mapping[str, Sequence[int]],
    signal_index: Mapping[tuple[int, int, str, str], float],
    cutoff_ms: int,
    hypothesis: Mapping[str, Any],
) -> dict[str, Any]:
    selected_values: list[float] = []
    by_pair: dict[str, list[float]] = defaultdict(list)
    by_timestamp: dict[int, list[float]] = defaultdict(list)
    feed_cost = DISCOVERY_COST_PIPS

    lookback = int(hypothesis["lookback"])
    horizon = int(hypothesis["horizon"])
    mode = str(hypothesis["mode"])
    orientation = str(hypothesis["orientation"])
    threshold = float(hypothesis["threshold"])
    candidate = {
        "lookback": lookback,
        "horizon": horizon,
        "mode": mode,
        "orientation": orientation,
        "threshold": threshold,
    }
    candidate_fp = candidate_fingerprint(candidate)

    for pair, positions in target_positions.items():
        feed = feeds[pair]
        for position in positions:
            timestamp_ms = int(feed.timestamps[position])
            signal = signal_index.get((timestamp_ms, lookback, pair, mode))
            if signal is None or not math.isfinite(signal) or abs(signal) < threshold:
                continue
            end_position = position + horizon
            if end_position >= len(feed.timestamps):
                continue
            target_end_ms = int(feed.timestamps[end_position])
            if target_end_ms >= cutoff_ms:
                continue
            if not _contiguous(feed.timestamps, position, end_position):
                continue

            direction = 1 if signal > 0.0 else -1
            if orientation == "reversion":
                direction *= -1
            if direction > 0:
                movement = (
                    feed.bid_close[end_position] - feed.ask_close[position]
                ) / PAIR_PIP[pair]
            else:
                movement = (
                    feed.bid_close[position] - feed.ask_close[end_position]
                ) / PAIR_PIP[pair]
            value = float(movement) - feed_cost
            selected_values.append(value)
            by_pair[pair].append(value)
            by_timestamp.setdefault(timestamp_ms, []).append(value)

    if not selected_values:
        return {
            **hypothesis,
            "candidate": candidate,
            "candidate_fingerprint": candidate_fp,
            "n": 0,
            "unique_timestamps": 0,
            "expectancy_pips": None,
            "profit_factor": None,
            "hac_one_sided_pvalue": 1.0,
            "ordinary_bootstrap_lower": math.nan,
            "cluster_block_bootstrap_lower": math.nan,
            "positive_pair_count": 0,
            "largest_pair_observation_share": 1.0,
            "passes_pre_holm": False,
            "stress": {},
        }

    timestamp_means = [
        mean(values)
        for _, values in sorted(by_timestamp.items())
    ]
    ordinary = bootstrap_means(
        selected_values,
        reps=BOOTSTRAP_REPS,
        seed=20260921 + lookback * 101 + horizon * 7,
    )
    cluster_lower = _clustered_block_lower(
        by_timestamp,
        reps=BOOTSTRAP_REPS,
        seed=20260921 + lookback * 101 + horizon * 7 + 1,
    )

    positive_pairs = sum(
        1
        for pair_values in by_pair.values()
        if len(pair_values) >= MIN_PAIR_TRADES
        and mean(pair_values) > MIN_EXPECTANCY_PIPS
        and (
            (pair_pf := profit_factor(pair_values)) is not None
            and float(pair_pf) > 1.0
        )
    )
    concentration = max(
        (len(pair_values) / len(selected_values) for pair_values in by_pair.values()),
        default=1.0,
    )
    expectancy = mean(selected_values)
    pf_value = profit_factor(selected_values)

    return {
        **hypothesis,
        "candidate": candidate,
        "candidate_fingerprint": candidate_fp,
        "n": len(selected_values),
        "unique_timestamps": len(by_timestamp),
        "expectancy_pips": expectancy,
        "profit_factor": pf_value,
        "hac_one_sided_pvalue": hac_mean_pvalue(timestamp_means),
        "ordinary_bootstrap_lower": float(ordinary[BOOTSTRAP_LOWER_INDEX]),
        "cluster_block_bootstrap_lower": cluster_lower,
        "positive_pair_count": positive_pairs,
        "largest_pair_observation_share": concentration,
        "stress": {
            str(cost): {
                "expectancy_pips": mean(value - cost for value in selected_values),
                "profit_factor": profit_factor([value - cost for value in selected_values]),
            }
            for cost in STRESS_COSTS_PIPS
        },
        "passes_pre_holm": (
            len(selected_values) >= MIN_DISCOVERY_TRADES
            and len(by_timestamp) >= MIN_TIMESTAMP_OBS
            and expectancy > MIN_EXPECTANCY_PIPS
            and pf_value is not None
            and float(pf_value) >= MIN_PROFIT_FACTOR
            and positive_pairs >= MIN_POSITIVE_PAIRS
            and concentration <= MAX_PAIR_CONCENTRATION
            and float(ordinary[BOOTSTRAP_LOWER_INDEX]) > 0.0
            and cluster_lower > 0.0
        ),
    }

def holm_adjust(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(results, key=lambda item: float(item["hac_one_sided_pvalue"]))
    m = len(ordered)
    previous = 0.0
    for index, item in enumerate(ordered):
        adjusted = min(1.0, max(previous, (m - index) * float(item["hac_one_sided_pvalue"])))
        item["holm_adjusted_pvalue"] = adjusted
        item["passes_familywise"] = bool(
            item["passes_pre_holm"]
            and adjusted <= FAMILY_ALPHA
        )
        previous = adjusted
    return ordered


def candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    payload = {
        "contract_version": CONTRACT_VERSION,
        "lookback": int(candidate["lookback"]),
        "horizon": int(candidate["horizon"]),
        "mode": str(candidate["mode"]),
        "orientation": str(candidate["orientation"]),
        "threshold": float(candidate["threshold"]),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def run_discovery(
    input_dir: Path,
    sample_stride: int,
) -> dict[str, Any]:
    if sample_stride <= 0:
        raise ValueError("sample_stride must be positive")
    feeds, source_manifest = load_feeds(input_dir)

    target_positions: dict[str, list[int]] = {}
    target_timestamps: set[int] = set()
    target_end_timestamps: set[int] = set()
    for pair, feed in feeds.items():
        positions: list[int] = []
        for position in range(
            max(LOOKBACKS),
            len(feed.timestamps) - max(HORIZONS),
            sample_stride,
        ):
            if not math.isfinite(float(feed.rolling_vol[position])):
                continue
            if not all(
                position + horizon < len(feed.timestamps)
                and _contiguous(feed.timestamps, position, position + horizon)
                for horizon in HORIZONS
            ):
                continue
            positions.append(position)
            timestamp_ms = int(feed.timestamps[position])
            target_timestamps.add(timestamp_ms)
            target_end_timestamps.update(
                timestamp_ms + horizon * 600_000
                for horizon in HORIZONS
            )
        target_positions[pair] = positions

    if not target_end_timestamps:
        raise ValueError("no valid target observations remain after continuity checks")
    cutoff_ms = sorted(target_end_timestamps)[
        int(len(target_end_timestamps) * DISCOVERY_FRACTION)
    ]

    signal_index = build_signal_index(feeds, sorted(target_timestamps))
    hypotheses = family_hypotheses()
    results = [
        _candidate_metrics(
            feeds,
            target_positions,
            signal_index,
            cutoff_ms,
            hypothesis,
        )
        for hypothesis in hypotheses
    ]
    results = holm_adjust(results)

    survivors = [
        result
        for result in results
        if bool(result.get("passes_familywise"))
    ]
    survivors.sort(
        key=lambda item: (
            float(item["holm_adjusted_pvalue"]),
            -float(item["expectancy_pips"] or -math.inf),
        )
    )
    top_candidates = [
        {
            **candidate,
            "candidate_fingerprint": candidate["candidate_fingerprint"],
        }
        for candidate in survivors[:10]
    ]
    status = (
        "CURRENCY_STRENGTH_DISCOVERY_COMPLETED"
        if results
        else "CURRENCY_STRENGTH_DISCOVERY_FAILED"
    )
    return {
        "status": status,
        "contract_version": CONTRACT_VERSION,
        "market_data_accessed": True,
        "live_execution_authorized": False,
        "promotion_authorized": False,
        "sample_stride": sample_stride,
        "lookbacks": LOOKBACKS,
        "horizons": HORIZONS,
        "thresholds": THRESHOLDS,
        "modes": MODES,
        "orientations": ORIENTATIONS,
        "discovery_family_size": len(results),
        "candidate_count": len(survivors),
        "candidate_selection_rule": "only a discovery-family result with all predefined robustness gates and family-wise Holm p <= 0.05 can become a candidate",
        "global_split_cutoff": datetime.fromtimestamp(
            cutoff_ms / 1000.0,
            tz=timezone.utc,
        ).isoformat(),
        "source_manifest": source_manifest,
        "target_timestamp_count": len(target_timestamps),
        "target_record_count": sum(len(values) for values in target_positions.values()),
        "top_candidates": top_candidates,
        "family_results": results,
        "selection_policy": {
            "contract_version": CONTRACT_VERSION,
            "selection_data": "discovery only",
            "confirmation_used_for_selection": False,
            "whole_family_holm": True,
            "holms_scope": len(results),
            "discovery_cost_pips": DISCOVERY_COST_PIPS,
            "minimum_discovery_trades": MIN_DISCOVERY_TRADES,
            "minimum_unique_timestamps": MIN_TIMESTAMP_OBS,
            "positive_pair_gate": MIN_POSITIVE_PAIRS,
            "minimum_pair_trades": MIN_PAIR_TRADES,
            "maximum_pair_concentration": MAX_PAIR_CONCENTRATION,
            "ordinary_bootstrap_repetitions": BOOTSTRAP_REPS,
            "cluster_block_bootstrap_repetitions": BOOTSTRAP_REPS,
            "stress_costs_pips": STRESS_COSTS_PIPS,
            "target_outcome_mechanics": "exact BID/ASK executable entry and exit; signal uses only prices available at the target close; complete target outcomes crossing the global split are excluded from discovery",
        },
    }

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Non-live cross-sectional currency-strength discovery over the verified nine-pair BID/ASK feed."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_discovery(Path(args.input_dir), args.sample_stride)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"CURRENCY_STRENGTH_DISCOVERY_STATUS={result['status']}")
    print(f"DISCOVERY_FAMILY_SIZE={result['discovery_family_size']}")
    print(f"CANDIDATE_COUNT={result['candidate_count']}")
    print(f"TARGET_RECORD_COUNT={result['target_record_count']}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
