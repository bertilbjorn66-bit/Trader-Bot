from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from .models import MarketBar, OfferSide


@dataclass(frozen=True)
class IntegrityReport:
    rows: int
    strictly_increasing: bool
    duplicate_timestamps: int
    invalid_spans: int
    missing_timestamps: int

    @property
    def ok(self) -> bool:
        return (
            self.rows > 0
            and self.strictly_increasing
            and self.duplicate_timestamps == 0
            and self.invalid_spans == 0
            and self.missing_timestamps == 0
        )


def validate_bars(bars: Sequence[MarketBar]) -> IntegrityReport:
    if not bars:
        return IntegrityReport(0, False, 0, 0, 0)

    ordered = sorted(bars, key=lambda x: x.timestamp)
    duplicates = sum(1 for a, b in zip(ordered, ordered[1:]) if a.timestamp == b.timestamp)
    invalid_spans = sum(1 for b in ordered if b.low > b.high or b.open < b.low or b.open > b.high or b.close < b.low or b.close > b.high)

    # For candle timeframes we can detect gaps from the expected interval.
    interval = {
        "10sec": timedelta(seconds=10),
        "1min": timedelta(minutes=1),
        "10m": timedelta(minutes=10),
        "1hour": timedelta(hours=1),
        "1day": timedelta(days=1),
        "1day_eet": timedelta(days=1),
    }.get(ordered[0].timeframe.value)

    missing = 0
    if interval:
        for a, b in zip(ordered, ordered[1:]):
            delta = b.timestamp - a.timestamp
            if delta > interval:
                missing += max(1, int(delta / interval) - 1)

    return IntegrityReport(
        rows=len(ordered),
        strictly_increasing=all(a.timestamp < b.timestamp for a, b in zip(ordered, ordered[1:])),
        duplicate_timestamps=duplicates,
        invalid_spans=invalid_spans,
        missing_timestamps=missing,
    )


def validate_bid_ask_alignment(bid: Sequence[MarketBar], ask: Sequence[MarketBar]) -> None:
    if any(x.offer_side != OfferSide.BID for x in bid):
        raise ValueError("BID collection contains a non-BID row")
    if any(x.offer_side != OfferSide.ASK for x in ask):
        raise ValueError("ASK collection contains a non-ASK row")
    bid_ts = [x.timestamp for x in bid]
    ask_ts = [x.timestamp for x in ask]
    if bid_ts != ask_ts:
        raise ValueError("BID and ASK timestamps do not align exactly")
