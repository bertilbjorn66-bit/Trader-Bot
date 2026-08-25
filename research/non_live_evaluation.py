from __future__ import annotations

from dataclasses import dataclass
import random
from statistics import mean
from typing import Sequence

from research.intelligence_audit import walk_forward_audit
from research.intelligence_controls import ExecutionCostModel


@dataclass(frozen=True)
class FoldResult:
    fold_id: int
    observations: int
    net_expectancy_pips: float
    profit_factor: float | None
    max_drawdown_pips: float
    positive: bool


@dataclass(frozen=True)
class DistributionAudit:
    mean_pips: float
    lower_bootstrap_mean: float
    upper_bootstrap_mean: float
    probability_positive_mean: float
    max_drawdown_pips: float
    ruin_probability: float


@dataclass(frozen=True)
class EvaluationVerdict:
    state: str
    reason: str
    folds_evaluated: int
    all_folds_positive: bool
    stress_resilient: bool
    uncertainty_supportive: bool
    max_drawdown_pips: float
    ruin_probability: float


def profit_factor(outcomes: Sequence[float]) -> float | None:
    gross_win = sum(value for value in outcomes if value > 0)
    gross_loss = -sum(value for value in outcomes if value < 0)
    if gross_loss == 0:
        return None
    return gross_win / gross_loss


def max_drawdown(outcomes: Sequence[float]) -> float:
    peak = 0.0
    balance = 0.0
    worst = 0.0
    for outcome in outcomes:
        balance += outcome
        peak = max(peak, balance)
        worst = min(worst, balance - peak)
    return abs(worst)


def bootstrap_means(outcomes: Sequence[float], reps: int = 2000, seed: int = 0) -> list[float]:
    if len(outcomes) < 2 or reps < 100:
        raise ValueError("bootstrap requires at least two outcomes and 100 repetitions")
    rng = random.Random(seed)
    n = len(outcomes)
    return sorted(mean(outcomes[rng.randrange(n)] for _ in range(n)) for _ in range(reps))


def block_bootstrap_means(outcomes: Sequence[float], block_size: int = 5, reps: int = 2000, seed: int = 0) -> list[float]:
    if len(outcomes) < 2 or block_size <= 0 or block_size > len(outcomes):
        raise ValueError("invalid block bootstrap parameters")
    if reps < 100:
        raise ValueError("block bootstrap requires 100 repetitions")
    rng = random.Random(seed)
    n = len(outcomes)
    blocks = [outcomes[index : index + block_size] for index in range(0, n, block_size)]
    result: list[float] = []
    for _ in range(reps):
        sample: list[float] = []
        while len(sample) < n:
            sample.extend(rng.choice(blocks))
        result.append(mean(sample[:n]))
    return sorted(result)


def probability_of_ruin(outcomes: Sequence[float], starting_capital_pips: float, simulations: int = 5000, horizon: int | None = None, seed: int = 0) -> float:
    if not outcomes or starting_capital_pips <= 0 or simulations < 100:
        raise ValueError("invalid ruin simulation inputs")
    horizon_value = horizon or len(outcomes)
    rng = random.Random(seed)
    ruined = 0
    for _ in range(simulations):
        capital = starting_capital_pips
        for _ in range(horizon_value):
            capital += rng.choice(outcomes)
            if capital <= 0:
                ruined += 1
                break
    return ruined / simulations


def distribution_audit(outcomes: Sequence[float], starting_capital_pips: float, reps: int = 2000, seed: int = 0) -> DistributionAudit:
    ordinary = bootstrap_means(outcomes, reps, seed)
    block = block_bootstrap_means(outcomes, min(5, len(outcomes)), reps, seed + 1)
    lower = min(ordinary[24], block[24])
    upper = max(ordinary[-25], block[-25])
    positive_probability = mean(value > 0 for value in ordinary)
    return DistributionAudit(
        mean(outcomes),
        lower,
        upper,
        positive_probability,
        max_drawdown(outcomes),
        probability_of_ruin(outcomes, starting_capital_pips, min(5000, reps * 2), len(outcomes), seed + 2),
    )


def apply_costs(outcomes: Sequence[float], cost: ExecutionCostModel) -> list[float]:
    net_cost = cost.total_cost_pips()
    return [value - net_cost for value in outcomes]


def evaluate_fold_series(outcomes: Sequence[float], folds: int, starting_capital_pips: float, cost: ExecutionCostModel) -> list[FoldResult]:
    if folds <= 0 or len(outcomes) < folds:
        raise ValueError("fold count must be positive and fit the observations")
    size = len(outcomes) // folds
    results: list[FoldResult] = []
    for fold_id in range(folds):
        start = fold_id * size
        end = len(outcomes) if fold_id == folds - 1 else (fold_id + 1) * size
        net = apply_costs(outcomes[start:end], cost)
        expectancy = mean(net)
        results.append(FoldResult(fold_id, len(net), expectancy, profit_factor(net), max_drawdown(net), expectancy > 0))
    return results


def evaluate_non_live(
    outcomes: Sequence[float],
    train_size: int,
    validation_size: int,
    step: int,
    costs: Sequence[tuple[str, ExecutionCostModel]],
    starting_capital_pips: float = 20.0,
) -> EvaluationVerdict:
    if len(outcomes) < train_size + validation_size:
        return EvaluationVerdict("INCOMPLETE", "insufficient observations for walk-forward evaluation", 0, False, False, False, 0.0, 1.0)
    walk_forward = walk_forward_audit(len(outcomes), train_size, validation_size, step)
    if not walk_forward.leakage_free:
        return EvaluationVerdict("INCOMPLETE", "walk-forward structure is not leakage-free", 0, False, False, False, 0.0, 1.0)
    base_cost = costs[0][1]
    fold_results = evaluate_fold_series(outcomes[train_size:], walk_forward.fold_count, starting_capital_pips, base_cost)
    all_positive = all(result.positive for result in fold_results)
    stress_positive = True
    for _, cost in costs:
        stressed = apply_costs(outcomes[train_size:], cost)
        stress_positive = stress_positive and mean(stressed) > 0
    dist = distribution_audit(apply_costs(outcomes[train_size:], base_cost), starting_capital_pips)
    uncertainty_supportive = dist.lower_bootstrap_mean > 0 and dist.probability_positive_mean >= 0.95 and dist.ruin_probability < 0.05
    worst_drawdown = max(result.max_drawdown_pips for result in fold_results)
    if all_positive and stress_positive and uncertainty_supportive:
        return EvaluationVerdict("PASS", "non-live evidence passed all predefined robustness conditions", len(fold_results), True, True, True, worst_drawdown, dist.ruin_probability)
    return EvaluationVerdict("FAIL", "non-live evidence did not satisfy all predefined robustness conditions", len(fold_results), all_positive, stress_positive, uncertainty_supportive, worst_drawdown, dist.ruin_probability)
