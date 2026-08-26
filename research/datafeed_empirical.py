from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator, cast

from trader_bot.data_provider import MarketDataProvider
from trader_bot.models import MarketBar, OfferSide, Timeframe
from trader_bot.providers.dukascopy import DukascopyProvider

from . import sequential_empirical as empirical
from .execution import ExecutionAssumptions

PAIR_TO_SYMBOL = {
    "EUR/USD": "eurusd", "GBP/USD": "gbpusd", "USD/JPY": "usdjpy", "AUD/USD": "audusd",
    "USD/CAD": "usdcad", "USD/CHF": "usdchf", "NZD/USD": "nzdusd", "EUR/JPY": "eurjpy",
    "GBP/JPY": "gbpjpy",
}
MAX_CROSSED_BAR_FRACTION = 0.001


def _number(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Feed field {key!r} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"Feed field {key!r} must be finite and strictly positive")
    return numeric


def _timestamp_ms(row: dict[str, object]) -> int:
    value = row.get("timestamp")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("Feed timestamp must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("Feed timestamp must be finite")
    return int(numeric)


def _validate_ohlc_geometry(item: dict[str, object], path: Path, line_number: int) -> None:
    for side in ("bid", "ask"):
        open_price = _number(item, f"{side}_open")
        high_price = _number(item, f"{side}_high")
        low_price = _number(item, f"{side}_low")
        close_price = _number(item, f"{side}_close")
        if low_price > min(open_price, close_price) or high_price < max(open_price, close_price) or low_price > high_price:
            raise ValueError(
                f"Invalid {side.upper()} OHLC geometry at {path}:{line_number} "
                f"(low={low_price}, open={open_price}, close={close_price}, high={high_price})"
            )


def _validate_bar(item: object, path: Path, line_number: int) -> dict[str, object]:
    if not isinstance(item, dict):
        raise ValueError(f"Invalid bar at {path}:{line_number}")
    _timestamp_ms(item)
    for key in (
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
    ):
        _number(item, key)
    _validate_ohlc_geometry(item, path, line_number)
    return dict(item)


def load_feed_bars(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Invalid feed record at {path}:{line_number}")
            if isinstance(payload.get("bars"), list):
                for item in payload["bars"]:
                    rows.append(_validate_bar(item, path, line_number))
            elif "timestamp" in payload:
                rows.append(_validate_bar(payload, path, line_number))
            else:
                raise ValueError(f"Invalid feed record at {path}:{line_number}")
    rows.sort(key=_timestamp_ms)
    if not rows:
        raise ValueError(f"No bars loaded for {path}")
    timestamps = [_timestamp_ms(row) for row in rows]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError(f"Duplicate timestamps in {path}")
    return rows


def _execution_valid_rows(rows: list[dict[str, object]], pair: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    valid: list[dict[str, object]] = []
    crossed = 0
    for row in rows:
        bid_open = _number(row, "bid_open")
        bid_close = _number(row, "bid_close")
        ask_open = _number(row, "ask_open")
        ask_close = _number(row, "ask_close")
        if ask_open < bid_open or ask_close < bid_close:
            crossed += 1
            continue
        valid.append(row)
    fraction = crossed / len(rows)
    if fraction > MAX_CROSSED_BAR_FRACTION:
        raise ValueError(
            f"{pair} has {crossed}/{len(rows)} crossed execution bars "
            f"({fraction:.4%}), above the {MAX_CROSSED_BAR_FRACTION:.2%} safety threshold"
        )
    return valid, {
        "input_bars": len(rows),
        "crossed_execution_bars_excluded": crossed,
        "crossed_execution_bar_fraction": fraction,
        "execution_bar_policy": "exclude ASK<BID open/close bars; never clip or repair prices",
    }


def _market_bars(rows: list[dict[str, object]]) -> tuple[tuple[MarketBar, ...], tuple[MarketBar, ...]]:
    bid: list[MarketBar] = []
    ask: list[MarketBar] = []
    for row in rows:
        timestamp = datetime.fromtimestamp(_timestamp_ms(row) / 1000, tz=timezone.utc)
        bid.append(MarketBar(
            timestamp=timestamp, instrument=1, timeframe=Timeframe.TEN_MINUTES, offer_side=OfferSide.BID,
            open=Decimal(str(_number(row, "bid_open"))), high=Decimal(str(_number(row, "bid_high"))),
            low=Decimal(str(_number(row, "bid_low"))), close=Decimal(str(_number(row, "bid_close"))),
        ))
        ask.append(MarketBar(
            timestamp=timestamp, instrument=1, timeframe=Timeframe.TEN_MINUTES, offer_side=OfferSide.ASK,
            open=Decimal(str(_number(row, "ask_open"))), high=Decimal(str(_number(row, "ask_high"))),
            low=Decimal(str(_number(row, "ask_low"))), close=Decimal(str(_number(row, "ask_close"))),
        ))
    return tuple(bid), tuple(ask)


def analyze_from_feed(
    pair: str,
    rows: list[dict[str, object]],
    start: datetime,
    end: datetime,
    sample_stride: int,
    history_states: int,
    max_days_per_batch: int,
    costs: ExecutionAssumptions,
) -> tuple[dict[str, object], list[tuple[datetime, float]]]:
    rows, quality = _execution_valid_rows(rows, pair)
    bid, ask = _market_bars(rows)
    original_iter = empirical.iter_bid_ask_batches  # type: ignore[attr-defined]

    def feed_iter(
        _provider: MarketDataProvider,
        _instrument_id: int,
        _timeframe: Timeframe,
        _start: datetime,
        _end: datetime,
        _max_days_per_batch: int = 7,
    ) -> Iterator[tuple[tuple[MarketBar, ...], tuple[MarketBar, ...]]]:
        yield bid, ask

    empirical.iter_bid_ask_batches = feed_iter  # type: ignore[attr-defined,assignment]
    try:
        report, returns = empirical.analyze_pair(
            cast(DukascopyProvider, object()), pair, 1, start, end, Timeframe.TEN_MINUTES,
            sample_stride, history_states, empirical.DEFAULT_HORIZONS, max_days_per_batch, costs,
        )
    finally:
        empirical.iter_bid_ask_batches = original_iter  # type: ignore[attr-defined]
    report["data_quality"] = quality
    return report, returns


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run leakage-safe empirical research from Dukascopy datafeed output.")
    parser.add_argument("--start", default="2020-01-01T00:00:00+00:00")
    parser.add_argument("--end", default=datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat())
    parser.add_argument("--pairs", default=",".join(PAIR_TO_SYMBOL))
    parser.add_argument("--input-dir", default=".data/empirical_feed")
    parser.add_argument("--sample-stride", type=int, default=120)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--max-days-per-batch", type=int, default=7)
    parser.add_argument("--output", default="artifacts/empirical_report.json")
    args = parser.parse_args()
    if args.sample_stride <= 0 or args.history_states <= 0 or args.max_days_per_batch <= 0:
        raise SystemExit("stride/history/max-days must be positive")
    return args


def main() -> None:
    args = parse_args()
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise SystemExit("start/end must be timezone-aware and start < end")
    pairs = tuple(item.strip() for item in args.pairs.split(",") if item.strip())
    unknown = [pair for pair in pairs if pair not in PAIR_TO_SYMBOL]
    if unknown:
        raise SystemExit(f"Unsupported datafeed pair(s): {', '.join(unknown)}")
    reports: list[dict[str, object]] = []
    series: dict[str, list[tuple[datetime, float]]] = {}
    costs = ExecutionAssumptions()
    input_dir = Path(args.input_dir)
    for pair in pairs:
        rows = load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl")
        report, returns = analyze_from_feed(pair, rows, start, end, args.sample_stride, args.history_states, args.max_days_per_batch, costs)
        reports.append(report)
        series[pair] = returns
    payload = {
        "research_status": "EMPIRICAL_DATAFEED_RUN_COMPLETED",
        "source": "Dukascopy public datafeed via dukascopy-go JETTA transport; native m5 aggregated to complete 10m bars",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pairs": reports,
        "cross_pair_return_correlation": empirical._correlation_matrix(pairs, series),
        "empirical": True,
        "synthetic": False,
        "permanent_raw_archive": False,
        "warning": "Research evidence only; no profitability guarantee and live execution remains disabled.",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
