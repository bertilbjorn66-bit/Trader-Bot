from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from .models import MarketBar, OfferSide, Timeframe


DERIVED_FROM: dict[str, tuple[Timeframe, int]] = {
    "5min": (Timeframe.ONE_MINUTE, 5),
    "15min": (Timeframe.ONE_MINUTE, 15),
    "4hour": (Timeframe.ONE_HOUR, 4),
}


def _bucket_start(ts: datetime, minutes: int) -> datetime:
    ts = ts.astimezone(timezone.utc)
    return ts.replace(minute=(ts.minute // minutes) * minutes, second=0, microsecond=0)


def aggregate_bars(bars: Sequence[MarketBar], target: str) -> list[MarketBar]:
    """Aggregate provider-native candles into 5m/15m/4h candles.

    Only complete buckets are emitted. This prevents a partial first/last bucket
    from contaminating downstream features. Session/market-closure completeness is
    handled separately by the trading-calendar validator.
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

    minutes = 60 if target == "4hour" else (15 if target == "15min" else 5)
    grouped: dict[datetime, list[MarketBar]] = defaultdict(list)
    for bar in sorted(bars, key=lambda x: x.timestamp):
        grouped[_bucket_start(bar.timestamp, minutes)].append(bar)

    output: list[MarketBar] = []
    for start, group in sorted(grouped.items()):
        group = sorted(group, key=lambda x: x.timestamp)
        if len(group) != expected:
            continue
        interval = timedelta(minutes=minutes if target != "4hour" else 240)
        if group[-1].timestamp - group[0].timestamp != interval - timedelta(minutes=1 if source_tf == Timeframe.ONE_MINUTE else 60):
            continue
        output.append(
            MarketBar(
                timestamp=start,
                instrument=group[0].instrument,
                timeframe=Timeframe.ONE_MINUTE if target in ("5min", "15min") else Timeframe.ONE_HOUR,
                offer_side=group[0].offer_side,
                open=group[0].open,
                high=max(x.high for x in group),
                low=min(x.low for x in group),
                close=group[-1].close,
                volume=sum((x.volume or Decimal("0")) for x in group),
            )
        )
    return output
