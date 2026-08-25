from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Mapping, Sequence

from research.intelligence_controls import (
    ExecutionCostModel,
    WalkForwardFold,
    make_walk_forward_folds,
    pearson_correlation,
)


@dataclass(frozen=True)
class CostStressPoint:
    label: str
    cost_pips: float
    net_expectancy_pips: float
    profitable: bool


def cost_stress_curve(gross_expectancy_pips: float, models: Mapping[str, ExecutionCostModel]) -> list[CostStressPoint]:
    points: list[CostStressPoint] = []
    for label, model in models.items():
        net = model.net_expectancy(gross_expectancy_pips)
        points.append(CostStressPoint(label, model.total_cost_pips(), net, net > 0))
    return points


@dataclass(frozen=True)
class LaggedRelation:
    lag: int
    correlation: float
    observations: int


def lagged_correlations(a: Sequence[float], b: Sequence[float], max_lag: int = 5) -> list[LaggedRelation]:
    if len(a) != len(b) or len(a) < 3:
        raise ValueError("lagged correlation requires aligned sequences with at least three observations")
    if max_lag < 0 or max_lag >= len(a) - 1:
        raise ValueError("max_lag must be non-negative and smaller than sequence length - 1")
    relations: list[LaggedRelation] = []
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            left = a[-lag:]
            right = b[:len(b) + lag]
        elif lag > 0:
            left = a[:len(a) - lag]
            right = b[lag:]
        else:
            left = a
            right = b
        relations.append(LaggedRelation(lag, pearson_correlation(left, right), len(left)))
    return relations


@dataclass(frozen=True)
class TransitionStat:
    from_state: str
    to_state: str
    observations: int
    probability: float
    mean_outcome: float


def regime_transition_stats(states: Sequence[str], outcomes: Sequence[float]) -> list[TransitionStat]:
    if len(states) != len(outcomes) or len(states) < 2:
        raise ValueError("transition analysis requires aligned sequences with at least two observations")
    counts: dict[tuple[str, str], int] = {}
    outcomes_by_transition: dict[tuple[str, str], list[float]] = {}
    totals: dict[str, int] = {}
    for index in range(len(states) - 1):
        key = (states[index], states[index + 1])
        counts[key] = counts.get(key, 0) + 1
        outcomes_by_transition.setdefault(key, []).append(float(outcomes[index + 1]))
        totals[states[index]] = totals.get(states[index], 0) + 1
    result: list[TransitionStat] = []
    for (from_state, to_state), count in sorted(counts.items()):
        vals = outcomes_by_transition[(from_state, to_state)]
        result.append(TransitionStat(from_state, to_state, count, count / totals[from_state], mean(vals)))
    return result


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    observations: int
    mean_probability: float
    empirical_rate: float


def calibration_bins(probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10) -> list[CalibrationBin]:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("probabilities and outcomes must be aligned and non-empty")
    if bins < 2:
        raise ValueError("bins must be at least two")
    result: list[CalibrationBin] = []
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [i for i, probability in enumerate(probabilities) if lower <= probability < upper or (index == bins - 1 and probability == upper)]
        if not members:
            continue
        result.append(CalibrationBin(lower, upper, len(members), mean(probabilities[i] for i in members), mean(outcomes[i] for i in members)))
    return result


@dataclass(frozen=True)
class WalkForwardAudit:
    folds: tuple[WalkForwardFold, ...]
    fold_count: int
    leakage_free: bool


def walk_forward_audit(total_observations: int, train_size: int, validation_size: int, step: int) -> WalkForwardAudit:
    folds = make_walk_forward_folds(total_observations, train_size, validation_size, step)
    leakage_free = all(fold.train_end < fold.validation_start for fold in folds)
    return WalkForwardAudit(tuple(folds), len(folds), leakage_free)


@dataclass(frozen=True)
class IntelligenceAuditSummary:
    cost_points: int
    lag_points: int
    transition_points: int
    calibration_bins: int
    walk_forward_folds: int
    ready_for_non_live_profitability_audit: bool


def summarize_audit(cost_points: Sequence[CostStressPoint], lag_points: Sequence[LaggedRelation], transition_points: Sequence[TransitionStat], calibration: Sequence[CalibrationBin], walk_forward: WalkForwardAudit) -> IntelligenceAuditSummary:
    return IntelligenceAuditSummary(
        len(cost_points),
        len(lag_points),
        len(transition_points),
        len(calibration),
        walk_forward.fold_count,
        walk_forward.leakage_free and walk_forward.fold_count > 0,
    )
