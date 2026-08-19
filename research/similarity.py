from __future__ import annotations

from math import sqrt
from collections.abc import Iterable

from .types import State


DEFAULT_FEATURES = (
    "trend",
    "trend_strength",
    "momentum",
    "volatility",
    "atr",
    "range",
    "distance_high",
    "distance_low",
    "spread",
)


def _numeric(state: State, names: Iterable[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for name in names:
        value = state.features.get(name)
        if isinstance(value, (int, float)) and value is not None:
            result[name] = float(value)
    return result


def fit_scaler(states: Iterable[State], features: Iterable[str] = DEFAULT_FEATURES) -> dict[str, tuple[float, float]]:
    values: dict[str, list[float]] = {name: [] for name in features}
    for state in states:
        row = _numeric(state, values)
        for name, value in row.items():
            values[name].append(value)
    scaler: dict[str, tuple[float, float]] = {}
    for name, xs in values.items():
        if not xs:
            continue
        mean = sum(xs) / len(xs)
        variance = sum((x - mean) ** 2 for x in xs) / max(len(xs) - 1, 1)
        scaler[name] = (mean, sqrt(variance) or 1.0)
    return scaler


def zscore_distance(a: State, b: State, scaler: dict[str, tuple[float, float]], features: Iterable[str] = DEFAULT_FEATURES) -> float:
    total = 0.0
    count = 0
    for name in features:
        if name not in scaler:
            continue
        av = a.features.get(name)
        bv = b.features.get(name)
        if not isinstance(av, (int, float)) or not isinstance(bv, (int, float)):
            continue
        mean, std = scaler[name]
        za = (float(av) - mean) / std
        zb = (float(bv) - mean) / std
        total += (za - zb) ** 2
        count += 1
    if count == 0:
        return float("inf")
    return sqrt(total / count)


def nearest_states(target: State, history: Iterable[State], scaler: dict[str, tuple[float, float]], k: int = 100) -> list[tuple[State, float]]:
    if k <= 0:
        raise ValueError("k must be positive")
    ranked = [(state, zscore_distance(target, state, scaler)) for state in history if state.timestamp < target.timestamp]
    ranked.sort(key=lambda item: item[1])
    return ranked[:k]
