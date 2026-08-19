from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

from trader_bot.models import MarketBar, OfferSide, Timeframe

from . import sequential_empirical as empirical

PAIR_TO_SYMBOL = {
    "EUR/USD": "eurusd",
    "GBP/USD": "gbpusd",
    "USD/JPY": "usdjpy",
    "AUD/USD": "audusd",
    "USD/CAD": "usdcad",
    "USD/CHF": "usdchf",
    "NZD/USD": "nzdusd",
    "EUR/JPY": "eurjpy",
    "GBP/JPY": "gbpjpy",
}


def _number(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"Feed field {key!r} must be numeric")
    return float(value)


def load_feed_bars(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
                raise ValueError(f"Invalid feed record at {path}:{line_number}")
            for item in payload["bars"]:
                if not isinstance(item, dict):
                    raise ValueError(f"Invalid bar at {path}:{line_number}")
                if not isinstance(item.get("timestamp"), (int, float)):
                    raise ValueError(f"Invalid timestamp at {path}:{line_number}")
                for key in ("bid_open", "bid_high", "bid_low", "bid_close", "ask_open", "ask_high", "ask_low", "ask_close"):
                    _number(item, key)
                rows.append(dict(item))
    rows.sort(key=lambda value: int(value["timestamp"]))
    if not rows:
        raise ValueError(f"No bars loaded for {path}")
    timestamps = [int(row["timestamp"]) for row in rows]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError(f"Duplicate timestamps in {path}")
    return rows


def _market_bars(rows: list[dict[str, object]]) -> tuple[tuple[MarketBar, ...], tuple[MarketBar, ...]]:
    bid: list[MarketBar] = []
    ask: list[MarketBar] = []
    for row in rows:
        timestamp = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=timezone.utc)
        bid.append(
            MarketBar(
                timestamp=timestamp,
                instrument=1,
                timeframe=Timeframe.TEN_MINUTES,
                offer_side=OfferSide.BID,
                open=Decimal(str(_number(row, "bid_open"))),
                high=Decimal(str(_number(row, "bid_high"))),
                low=Decimal(str(_number(row, "bid_low"))),
                close=Decimal(str(_number(row, "bid_close"))),
            )
        )
        ask.append(
            MarketBar(
                timestamp=timestamp,
                instrument=1,
                timeframe=Timeframe.TEN_MINUTES,
                offer_side=OfferSide.ASK,
                open=Decimal(str(_number(row, "ask_open"))),
                high=Decimal(str(_number(row, "ask_high"))),
                low=Decimal(str(_number(row, "ask_low"))),
                close=Decimal(str(_number(row, "ask_close"))),
            )
        )
    return tuple(bid), tuple(ask)


def analyze_from_feed(
    pair: str,
    rows: list[dict[str, object]],
    start: datetime,
    end: datetime,
    sample_stride: int,
    history_states: int,
    max_days_per_batch: int,
    costs: empirical.ExecutionAssumptions,
) -> tuple[dict[str, object], list[tuple[datetime, float]]]:
    bid, ask = _market_bars(rows)
    original_iter = empirical.iter_bid_ask_batches

    def feed_iter(
        _provider: object,
        _instrument_id: int,
        _timeframe: Timeframe,
        _start: datetime,
        _end: datetime,
        _max_days_per_batch: int,
    ) -> Iterator[tuple[tuple[MarketBar, ...], tuple[MarketBar, ...]]]:
        yield bid, ask

    empirical.iter_bid_ask_batches = feed_iter  # type: ignore[assignment]
    try:
        report, returns = empirical.analyze_pair(
            SimpleNamespace(),
            pair,
            1,
            start,
            end,
            Timeframe.TEN_MINUTES,
            sample_stride,
            history_states,
            empirical.DEFAULT_HORIZONS,
            max_days_per_batch,
            costs,
        )
    finally:
        empirical.iter_bid_ask_batches = original_iter
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
    costs = empirical.ExecutionAssumptions()
    input_dir = Path(args.input_dir)
    for pair in pairs:
        rows = load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl")
        report, returns = analyze_from_feed(
            pair,
            rows,
            start,
            end,
            args.sample_stride,
            args.history_states,
            args.max_days_per_batch,
            costs,
        )
        reports.append(report)
        series[pair] = returns

    payload = {
        "research_status": "EMPIRICAL_DATAFEED_RUN_COMPLETED",
        "source": "Dukascopy public datafeed via dukascopy-node; native m5 aggregated to complete 10m bars",
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
