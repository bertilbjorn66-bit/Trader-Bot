from __future__ import annotations

from math import sqrt
from statistics import mean, median
from typing import Sequence


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0 or successes < 0 or successes > n:
        raise ValueError("invalid binomial counts")
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def probability_summary(values: Sequence[float], threshold: float = 0.0) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "probability": None, "ci_low": None, "ci_high": None, "mean": None, "median": None}
    n = len(values)
    successes = sum(v > threshold for v in values)
    lo, hi = wilson_interval(successes, n)
    return {"n": n, "probability": successes / n, "ci_low": lo, "ci_high": hi, "mean": mean(values), "median": median(values)}


def expectancy(values: Sequence[float], transaction_cost: float = 0.0) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "expectancy": None, "win_rate": None, "avg_win": None, "avg_loss": None, "profit_factor": None}
    net = [v - transaction_cost for v in values]
    wins = [v for v in net if v > 0]
    losses = [v for v in net if v < 0]
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


def multiple_testing_bonferroni(p_values: Sequence[float]) -> list[float]:
    m = len(p_values)
    if m == 0:
        return []
    return [min(1.0, p * m) for p in p_values]
