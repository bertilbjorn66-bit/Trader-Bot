from __future__ import annotations

from math import sqrt
from statistics import mean, median
from typing import Sequence


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0 or successes < 0 or successes > n:
        raise ValueError("invalid binomial counts")
    if z <= 0:
        raise ValueError("z must be positive")
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def probability_summary(values: Sequence[float], threshold: float = 0.0) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "probability": None, "ci_low": None, "ci_high": None, "mean": None, "median": None}
    n = len(values)
    successes = sum(value > threshold for value in values)
    lo, hi = wilson_interval(successes, n)
    return {"n": n, "probability": successes / n, "ci_low": lo, "ci_high": hi, "mean": mean(values), "median": median(values)}


def expectancy(values: Sequence[float], transaction_cost: float = 0.0) -> dict[str, float | int | None]:
    if transaction_cost < 0:
        raise ValueError("transaction_cost cannot be negative")
    if not values:
        return {"n": 0, "expectancy": None, "win_rate": None, "avg_win": None, "avg_loss": None, "profit_factor": None}
    net = [value - transaction_cost for value in values]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    return {
        "n": len(net),
        "expectancy": mean(net),
        "win_rate": len(wins) / len(net),
        "avg_win": mean(wins) if wins else 0.0,
        "avg_loss": mean(losses) if losses else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
    }


def max_drawdown(returns: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return -worst


def _validate_p_values(p_values: Sequence[float]) -> None:
    if any(p < 0 or p > 1 for p in p_values):
        raise ValueError("p-values must be within [0, 1]")


def multiple_testing_bonferroni(p_values: Sequence[float]) -> list[float]:
    _validate_p_values(p_values)
    m = len(p_values)
    return [] if m == 0 else [min(1.0, p * m) for p in p_values]


def multiple_testing_holm(p_values: Sequence[float]) -> list[float]:
    _validate_p_values(p_values)
    m = len(p_values)
    adjusted = [0.0] * m
    order = sorted(range(m), key=lambda index: p_values[index])
    running = 0.0
    for rank, index in enumerate(order, start=1):
        running = max(running, min(1.0, p_values[index] * (m - rank + 1)))
        adjusted[index] = running
    return adjusted


def multiple_testing_bh_fdr(p_values: Sequence[float]) -> list[float]:
    _validate_p_values(p_values)
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda index: p_values[index])
    adjusted = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        index = order[rank - 1]
        running = min(running, p_values[index] * m / rank)
        adjusted[index] = min(1.0, running)
    return adjusted
