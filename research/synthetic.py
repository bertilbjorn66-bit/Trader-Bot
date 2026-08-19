from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .types import Bar


def generate_bars(n: int = 500, start: datetime | None = None, seed: int = 7) -> list[Bar]:
    """Generate deterministic synthetic BID/ASK bars for pipeline tests only.

    This data has no financial meaning and must never be presented as empirical market results.
    """
    if n < 80:
        raise ValueError("n must be at least 80")
    if start is None:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    x = 1.1000
    bars: list[Bar] = []
    state = seed % 97
    for i in range(n):
        phase = math.sin(i / 17.0) * 0.0005 + math.sin(i / 43.0) * 0.0008
        drift = 0.00002 if (i // 60) % 2 == 0 else -0.000015
        prev = x
        x = max(0.5, x + drift + phase * 0.03 + ((state * 17 + i * 13) % 23 - 11) * 0.000002)
        spread = 0.00008 + abs(math.sin(i / 31.0)) * 0.00004
        high = max(prev, x) + 0.00004 + abs(math.sin(i / 7.0)) * 0.00003
        low = min(prev, x) - 0.00004 - abs(math.cos(i / 9.0)) * 0.00003
        bars.append(
            Bar(
                timestamp=start + timedelta(minutes=i),
                bid_open=prev,
                bid_high=high,
                bid_low=low,
                bid_close=x,
                ask_open=prev + spread,
                ask_high=high + spread,
                ask_low=low + spread,
                ask_close=x + spread,
                spread_open=spread,
                spread_high=spread,
                spread_low=spread,
                spread_close=spread,
            )
        )
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
    return bars
