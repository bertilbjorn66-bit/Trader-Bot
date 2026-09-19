from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import sqrt

import numpy as np
from numpy.typing import NDArray

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


class SimilarityIndex:
    """Precompute state features for fast rolling exact-semantics neighbor queries."""

    def __init__(self, states: Sequence[State], features: Iterable[str] = DEFAULT_FEATURES) -> None:
        self.states = list(states)
        self.features = tuple(features)
        self._matrix: NDArray[np.float64] | None = None
        if not self.states or not self.features:
            return
        rows: list[list[float]] = []
        for state in self.states:
            row: list[float] = []
            for name in self.features:
                value = state.features.get(name)
                if not isinstance(value, (int, float)) or value is None:
                    return
                row.append(float(value))
            rows.append(row)
        self._matrix = np.asarray(rows, dtype=np.float64)

    def fit_scaler(self, start: int, end: int) -> dict[str, tuple[float, float]]:
        if not 0 <= start <= end <= len(self.states):
            raise ValueError("invalid scaler window")
        if self._matrix is None:
            return fit_scaler(self.states[start:end], self.features)
        block = self._matrix[start:end]
        if len(block) == 0:
            return {}
        scaler: dict[str, tuple[float, float]] = {}
        for index, name in enumerate(self.features):
            values = block[:, index]
            centre = float(np.mean(values))
            variance = float(np.sum((values - centre) ** 2) / max(len(values) - 1, 1))
            scaler[name] = (centre, sqrt(variance) or 1.0)
        return scaler

    def nearest(
        self,
        target: State,
        start: int,
        end: int,
        scaler: dict[str, tuple[float, float]],
        k: int = 100,
    ) -> list[tuple[State, float]]:
        if k <= 0:
            raise ValueError("k must be positive")
        if not 0 <= start <= end <= len(self.states):
            raise ValueError("invalid neighbor window")
        history = self.states[start:end]
        if not history:
            return []

        active = [
            name
            for name in self.features
            if name in scaler
            and isinstance(target.features.get(name), (int, float))
            and target.features.get(name) is not None
        ]
        if self._matrix is None or len(active) != len(self.features):
            return nearest_states(target, history, scaler, k=k)

        stds = np.asarray([scaler[name][1] for name in self.features], dtype=np.float64)
        target_values = np.asarray(
            [float(target.features[name]) for name in self.features],
            dtype=np.float64,
        )
        block = self._matrix[start:end]
        distances_squared = np.mean(((block - target_values) / stds) ** 2, axis=1)
        pool_size = min(len(history), max(k + 64, k * 8))
        if pool_size < len(history):
            boundary = float(np.partition(distances_squared, k - 1)[k - 1])
            tolerance = max(1e-12, abs(boundary) * 1e-12)
            near_boundary = np.flatnonzero(distances_squared <= boundary + tolerance)
            candidate_indices = near_boundary.tolist()
            if len(candidate_indices) < pool_size:
                candidate_indices = np.argsort(distances_squared, kind="stable")[:pool_size].tolist()
        else:
            candidate_indices = np.arange(len(history)).tolist()
        ordered_indices = candidate_indices

        exact_ranked = [
            (history[int(index)], zscore_distance(target, history[int(index)], scaler, self.features))
            for index in ordered_indices
        ]
        exact_ranked.sort(key=lambda item: item[1])
        return exact_ranked[:k]


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
