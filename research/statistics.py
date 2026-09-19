from __future__ import annotations

from math import erfc, sqrt
from statistics import mean, median
from typing import Sequence

from .multiple_testing import benjamini_hochberg, bonferroni, holm_bonferroni


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


HAC_DEFAULT_LAG = 5


def hac_mean_pvalue(values: Sequence[float], max_lag: int = HAC_DEFAULT_LAG) -> float:
    """One-sided HAC-normal p-value for positive mean under time dependence."""
    if len(values) < 2:
        raise ValueError("HAC p-value requires at least two observations")
    if max_lag < 0 or max_lag >= len(values):
        raise ValueError("invalid HAC lag")
    centre = mean(values)
    centred = [value - centre for value in values]
    gamma_0 = mean(value * value for value in centred)
    variance = gamma_0
    for lag in range(1, max_lag + 1):
        gamma = mean(
            centred[index] * centred[index - lag]
            for index in range(lag, len(values))
        )
        weight = 1.0 - lag / (max_lag + 1.0)
        variance += 2.0 * weight * gamma
    variance = max(variance, 0.0)
    standard_error = sqrt(variance / len(values))
    if standard_error == 0.0:
        return 0.0 if centre > 0.0 else 1.0
    z = centre / standard_error
    return 0.5 * erfc(z / sqrt(2.0))


def max_drawdown(returns: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return -worst


# Backward-compatible aliases; canonical implementations live in research.multiple_testing.
def multiple_testing_bonferroni(p_values: Sequence[float]) -> list[float]:
    return bonferroni(p_values)


def multiple_testing_holm(p_values: Sequence[float]) -> list[float]:
    return holm_bonferroni(p_values)


def multiple_testing_bh_fdr(p_values: Sequence[float]) -> list[float]:
    return benjamini_hochberg(p_values)
