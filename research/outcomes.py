from __future__ import annotations

from math import isfinite
from typing import Sequence

from .types import Bar, Outcome


def future_outcome(
    bars: Sequence[Bar],
    index: int,
    horizon: int,
    direction: str,
    target: float | None = None,
    stop: float | None = None,
) -> Outcome:
    if direction not in {"long", "short"}:
        raise ValueError("direction must be long or short")
    if horizon <= 0 or index < 0 or index >= len(bars):
        raise ValueError("invalid index/horizon")
    end = min(index + horizon, len(bars) - 1)
    if end <= index:
        raise ValueError("future window is empty")

    entry_bar = bars[index]
    entry = entry_bar.ask_close if direction == "long" else entry_bar.bid_close
    future = bars[index + 1 : end + 1]
    if direction == "long":
        favorable = max(b.bid_high - entry for b in future)
        adverse = max(entry - b.bid_low for b in future)
        exit_price = bars[end].bid_close
        movement = exit_price - entry
    else:
        favorable = max(entry - b.ask_low for b in future)
        adverse = max(b.ask_high - entry for b in future)
        exit_price = bars[end].ask_close
        movement = entry - exit_price

    hit: bool | None = None
    if target is not None and stop is not None:
        if target <= 0 or stop <= 0:
            raise ValueError("target and stop must be positive distances")
        for bar in future:
            if direction == "long":
                target_hit = bar.bid_high >= entry + target
                stop_hit = bar.bid_low <= entry - stop
            else:
                target_hit = bar.ask_low <= entry - target
                stop_hit = bar.ask_high >= entry + stop
            if target_hit and stop_hit:
                hit = None
                break
            if target_hit:
                hit = True
                break
            if stop_hit:
                hit = False
                break

    values = (entry, exit_price, movement, favorable, adverse)
    if not all(isfinite(value) for value in values):
        raise ValueError("non-finite outcome")
    return Outcome(bars[index].timestamp, horizon, direction, entry, exit_price, movement, favorable, adverse, hit)


def horizon_outcomes(bars: Sequence[Bar], index: int, horizons: Sequence[int], direction: str) -> list[Outcome]:
    return [
        future_outcome(bars, index, horizon, direction)
        for horizon in horizons
        if index + horizon <= len(bars) - 1
    ]
