from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from .models import MarketBar, Timeframe


DERIVED_FROM: dict[Timeframe, tuple[Timeframe, int]] = {
    Timeframe.FIVE_MINUTES: (Timeframe.ONE_MINUTE, 5),
    Timeframe.FIFTEEN_MINUTES: (Timeframe.ONE_MINUTE, 15),
    Timeframe.FOUR_HOURS: (Timeframe.ONE_HOUR, 4),
}


def _bucket_start(ts: datetime, minutes: int) -> datetime:
    ts = ts.astimezone(timezone.utc)
    if minutes >= 60:
        hours = minutes // 60
        return ts.replace(hour=(ts.hour // hours) * hours, minute=0, second=0, microsecond=0)
    return ts.replace(minute=(ts.minute // minutes) * minutes, second=0, microsecond=0)


def aggregate_bars(bars: Sequence[MarketBar], target: Timeframe) -> list[MarketBar]:
    """Aggregate provider-native candles into 5m/15m/4h candles.

    Only complete buckets are emitted. A separate market-calendar validator is
    required before interpreting gaps as corruption because FX has closure periods.
    """
    if target not in DERIVED_FROM:
        raise ValueError(f"Unsupported derived timeframe: {target}")
    source_tf, expected = DERIVED_FROM[target]
    if not bars:
        return []
    if any(b.timeframe != source_tf for b in bars):
        raise ValueError("All source bars must use the required provider-native timeframe")
    if any(b.offer_side != bars[0].offer_side for b in bars):
        raise ValueError("All bars must have the same offer side")

    minutes = 240 if target == Timeframe.FOUR_HOURS else (15 if target == Timeframe.FIFTEEN_MINUTES else 5)
    grouped: dict[datetime, list[MarketBar]] = defaultdict(list)
    for bar in sorted(bars, key=lambda x: x.timestamp):
        grouped[_bucket_start(bar.timestamp, minutes)].append(bar)

    output: list[MarketBar] = []
    for start, group in sorted(grouped.items()):
        group = sorted(group, key=lambda x: x.timestamp)
        if len(group) != expected:
            continue
        expected_span = timedelta(minutes=minutes) - (
            timedelta(minutes=1) if source_tf == Timeframe.ONE_MINUTE else timedelta(hours=1)
        )
        if group[-1].timestamp - group[0].timestamp != expected_span:
            continue
        output.append(
            MarketBar(
                timestamp=start,
                instrument=group[0].instrument,
                timeframe=target,
                offer_side=group[0].offer_side,
                open=group[0].open,
                high=max(x.high for x in group),
                low=min(x.low for x in group),
                close=group[-1].close,
                volume=sum((x.volume or Decimal("0")) for x in group),
            )
        )
    return output
