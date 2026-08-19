from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .models import MarketBar, Timeframe
from .validation import validate_bar_sequence


SUPPORTED_AGGREGATIONS = {
    Timeframe.FIVE_MINUTES: (5, Timeframe.ONE_MINUTE),
    Timeframe.FIFTEEN_MINUTES: (15, Timeframe.ONE_MINUTE),
    Timeframe.FOUR_HOURS: (4, Timeframe.ONE_HOUR),
}


def aggregate_bars(group: Sequence[MarketBar], target: Timeframe) -> MarketBar:
    if not group:
        raise ValueError("cannot aggregate an empty group")
    target_size, source = SUPPORTED_AGGREGATIONS[target]
    if len(group) != target_size:
        raise ValueError("group length does not match target timeframe")
    if any(bar.timeframe is not source for bar in group):
        raise ValueError("source timeframe mismatch")
    start = group[0].timestamp
    expected_span = group[-1].timestamp - start
    if expected_span.total_seconds() != (target_size - 1) * {
        Timeframe.ONE_MINUTE: 60,
        Timeframe.ONE_HOUR: 3600,
    }[source]:
        raise ValueError("group has a timestamp gap")
    volumes = [bar.volume for bar in group]
    total_volume = sum((v for v in volumes if v is not None), Decimal("0")) if any(v is not None for v in volumes) else None
    return MarketBar(
        timestamp=start,
        instrument=group[0].instrument,
        timeframe=target,
        offer_side=group[0].offer_side,
        open=group[0].open,
        high=max(x.high for x in group),
        low=min(x.low for x in group),
        close=group[-1].close,
        volume=total_volume,
    )


def aggregate_series(bars: Sequence[MarketBar], target: Timeframe) -> list[MarketBar]:
    if target not in SUPPORTED_AGGREGATIONS:
        raise ValueError("unsupported target timeframe")
    if not bars:
        return []
    validate_bar_sequence(bars)
    size, source = SUPPORTED_AGGREGATIONS[target]
    if any(bar.timeframe is not source for bar in bars):
        raise ValueError("source timeframe mismatch")
    output: list[MarketBar] = []
    for i in range(0, len(bars), size):
        group = bars[i : i + size]
        if len(group) != size:
            continue
        try:
            output.append(aggregate_bars(group, target))
        except ValueError:
            continue
    return output
