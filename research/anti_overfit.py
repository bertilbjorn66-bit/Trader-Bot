from __future__ import annotations

from dataclasses import dataclass
from math import log
from statistics import mean
from typing import Sequence


@dataclass(frozen=True, slots=True)
class TrialSummary:
    trial_count: int
    best_oos_score: float
    median_oos_score: float
    uplift_over_median: float
    selection_risk: float


@dataclass(frozen=True, slots=True)
class PerturbationResult:
    baseline_score: float
    perturbed_scores: tuple[float, ...]
    worst_score: float
    degradation_fraction: float
    robust: bool


def summarize_trials(oos_scores: Sequence[float]) -> TrialSummary:
    if not oos_scores:
        raise ValueError("oos_scores cannot be empty")
    if any(score != score for score in oos_scores):
        raise ValueError("oos_scores cannot contain NaN")
    ordered = sorted(float(score) for score in oos_scores)
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    best = ordered[-1]
    uplift = best - median
    # This is a transparent screening statistic, not a formal PBO estimator.
    selection_risk = min(1.0, max(0.0, log(max(len(ordered), 1)) / 10.0))
    return TrialSummary(len(ordered), best, median, uplift, selection_risk)


def perturbation_audit(
    baseline_score: float,
    perturbed_scores: Sequence[float],
    *,
    maximum_degradation_fraction: float = 0.50,
) -> PerturbationResult:
    if not perturbed_scores:
        raise ValueError("perturbed_scores cannot be empty")
    if baseline_score <= 0:
        raise ValueError("baseline_score must be positive for relative degradation testing")
    if not 0.0 <= maximum_degradation_fraction < 1.0:
        raise ValueError("maximum_degradation_fraction must be in [0, 1)")
    scores = tuple(float(score) for score in perturbed_scores)
    worst = min(scores)
    degradation = max(0.0, (baseline_score - worst) / baseline_score)
    return PerturbationResult(
        baseline_score=baseline_score,
        perturbed_scores=scores,
        worst_score=worst,
        degradation_fraction=degradation,
        robust=degradation <= maximum_degradation_fraction and all(score > 0 for score in scores),
    )


def stability_ratio(scores: Sequence[float]) -> float:
    if not scores:
        raise ValueError("scores cannot be empty")
    return sum(score > 0 for score in scores) / len(scores)


def mean_positive(scores: Sequence[float]) -> float:
    if not scores:
        raise ValueError("scores cannot be empty")
    positive = [score for score in scores if score > 0]
    return mean(positive) if positive else 0.0
