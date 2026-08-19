from __future__ import annotations

from collections.abc import Sequence


def bonferroni(p_values: Sequence[float]) -> list[float]:
    """Family-wise error correction for exploratory strategy searches."""
    m = len(p_values)
    if any(p < 0 or p > 1 for p in p_values):
        raise ValueError("p-values must lie in [0, 1]")
    if not m:
        return []
    return [min(1.0, p * m) for p in p_values]


def holm_bonferroni(p_values: Sequence[float]) -> list[float]:
    """Step-down family-wise error correction, returned in original order."""
    if any(p < 0 or p > 1 for p in p_values):
        raise ValueError("p-values must lie in [0, 1]")
    m = len(p_values)
    order = sorted(range(m), key=p_values.__getitem__)
    adjusted = [0.0] * m
    running = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, (m - rank) * p_values[index])
        running = max(running, value)
        adjusted[index] = running
    return adjusted


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """False-discovery-rate adjustment, returned in original order."""
    if any(p < 0 or p > 1 for p in p_values):
        raise ValueError("p-values must lie in [0, 1]")
    m = len(p_values)
    if not m:
        return []
    order = sorted(range(m), key=p_values.__getitem__)
    adjusted = [1.0] * m
    running = 1.0
    for rank in range(m - 1, -1, -1):
        index = order[rank]
        value = min(1.0, p_values[index] * m / (rank + 1))
        running = min(running, value)
        adjusted[index] = running
    return adjusted
