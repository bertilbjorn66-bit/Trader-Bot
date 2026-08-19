from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Sequence

from .context import MarketState


@dataclass(frozen=True)
class ComparableState:
    state: MarketState
    distance: float


def _vector(s: MarketState) -> tuple[float, ...]:
    return (
        s.return_5,
        s.return_20,
        float(s.range_20),
        float(s.range_60),
        s.volatility_20,
        s.volatility_60,
        s.trend_fast_slow,
        float(s.spread),
    )


def distance(a: MarketState, b: MarketState) -> float:
    av, bv = _vector(a), _vector(b)
    scales = tuple(max(abs(x), abs(y), 1e-12) for x, y in zip(av, bv))
    return sqrt(sum(((x - y) / scale) ** 2 for x, y, scale in zip(av, bv, scales)))


def nearest(target: MarketState, candidates: Sequence[MarketState], limit: int = 100) -> list[ComparableState]:
    if limit <= 0:
        return []
    # Critical leakage rule: a candidate at or after the target timestamp is never eligible.
    eligible = (c for c in candidates if c.timestamp < target.timestamp)
    return sorted((ComparableState(c, distance(target, c)) for c in eligible), key=lambda x: x.distance)[:limit]
