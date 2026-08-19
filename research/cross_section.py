from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from math import sqrt
from typing import Mapping


def session_label(ts: datetime) -> str:
    if ts.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    hour = ts.astimezone(timezone.utc).hour
    if hour < 7:
        return "asia"
    if hour < 13:
        return "london"
    if hour < 21:
        return "new_york"
    return "rollover"


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("series must have equal length >= 2")
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    da = [x - ma for x in a]
    db = [y - mb for y in b]
    den = sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    return sum(x * y for x, y in zip(da, db, strict=True)) / den if den else 0.0


def correlation_matrix(series: Mapping[str, Sequence[float]]) -> dict[str, dict[str, float]]:
    names = list(series)
    return {a: {b: pearson(series[a], series[b]) for b in names} for a in names}
