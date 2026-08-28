from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ComparableState:
    instrument: str
    asset_class: str
    timestamp: int
    regime: str
    features: Mapping[str, float]
    expected_return: float
    uncertainty: float
    liquidity_score: float


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    left: str
    right: str
    common_features: tuple[str, ...]
    similarity: float
    expected_return_difference: float
    uncertainty_difference: float
    liquidity_difference: float


def _distance(a: Mapping[str, float], b: Mapping[str, float], features: Sequence[str]) -> float:
    values: list[float] = []
    for name in features:
        if name not in a or name not in b:
            continue
        values.append((float(a[name]) - float(b[name])) ** 2)
    if not values:
        return float("inf")
    return sqrt(mean(values))


def compare_states(left: ComparableState, right: ComparableState) -> ComparisonResult:
    common = tuple(sorted(set(left.features) & set(right.features)))
    distance = _distance(left.features, right.features, common)
    similarity = 1.0 / (1.0 + distance) if distance != float("inf") else 0.0
    return ComparisonResult(
        left=left.instrument,
        right=right.instrument,
        common_features=common,
        similarity=similarity,
        expected_return_difference=left.expected_return - right.expected_return,
        uncertainty_difference=left.uncertainty - right.uncertainty,
        liquidity_difference=left.liquidity_score - right.liquidity_score,
    )


def rank_opportunities(states: Sequence[ComparableState]) -> tuple[ComparableState, ...]:
    """Rank opportunities without allowing raw expected return to dominate risk and uncertainty."""
    def score(state: ComparableState) -> float:
        return state.expected_return * state.liquidity_score / (1.0 + max(state.uncertainty, 0.0))

    return tuple(sorted(states, key=score, reverse=True))


def pairwise_matrix(states: Sequence[ComparableState]) -> dict[str, dict[str, float]]:
    matrix: dict[str, dict[str, float]] = {}
    for left in states:
        matrix[left.instrument] = {}
        for right in states:
            matrix[left.instrument][right.instrument] = compare_states(left, right).similarity
    return matrix
