from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Sequence


class HealthState:
    HEALTHY = "HEALTHY"
    CAUTIOUS = "CAUTIOUS"
    DEFENSIVE = "DEFENSIVE"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"


@dataclass(frozen=True, slots=True)
class HealthMetrics:
    recent_expectancy: float
    reference_expectancy: float
    recent_volatility: float
    reference_volatility: float
    recent_error_rate: float
    reference_error_rate: float


@dataclass(frozen=True, slots=True)
class HealthAssessment:
    state: str
    reasons: tuple[str, ...]
    metrics: HealthMetrics


def assess_model_health(
    recent_outcomes: Sequence[float],
    reference_outcomes: Sequence[float],
    *,
    recent_error_rate: float = 0.0,
    reference_error_rate: float = 0.0,
    cautious_shift: float = 0.25,
    defensive_shift: float = 0.50,
) -> HealthAssessment:
    if len(recent_outcomes) < 2 or len(reference_outcomes) < 2:
        raise ValueError("health assessment requires at least two outcomes in each window")
    if not 0.0 <= recent_error_rate <= 1.0 or not 0.0 <= reference_error_rate <= 1.0:
        raise ValueError("error rates must be in [0, 1]")
    if not 0.0 <= cautious_shift < defensive_shift:
        raise ValueError("health thresholds must satisfy 0 <= cautious < defensive")

    recent_mean = mean(recent_outcomes)
    reference_mean = mean(reference_outcomes)
    recent_vol = pstdev(recent_outcomes)
    reference_vol = pstdev(reference_outcomes)
    expectancy_shift = abs(recent_mean - reference_mean) / max(abs(reference_mean), 1e-9)
    volatility_ratio = recent_vol / max(reference_vol, 1e-9)
    error_shift = abs(recent_error_rate - reference_error_rate)

    reasons: list[str] = []
    severity = 0
    if expectancy_shift >= defensive_shift:
        severity = max(severity, 3)
        reasons.append("expectancy_shift_defensive")
    elif expectancy_shift >= cautious_shift:
        severity = max(severity, 1)
        reasons.append("expectancy_shift_cautious")
    if volatility_ratio >= 2.0:
        severity = max(severity, 2)
        reasons.append("volatility_doubled")
    elif volatility_ratio >= 1.5:
        severity = max(severity, 1)
        reasons.append("volatility_elevated")
    if error_shift >= 0.20:
        severity = max(severity, 3)
        reasons.append("error_rate_shift_defensive")
    elif error_shift >= 0.10:
        severity = max(severity, 1)
        reasons.append("error_rate_shift_cautious")
    if recent_mean <= 0.0:
        severity = max(severity, 2)
        reasons.append("recent_expectancy_non_positive")

    state = {
        0: HealthState.HEALTHY,
        1: HealthState.CAUTIOUS,
        2: HealthState.DEFENSIVE,
        3: HealthState.OBSERVATION_ONLY,
    }[severity]
    metrics = HealthMetrics(recent_mean, reference_mean, recent_vol, reference_vol, recent_error_rate, reference_error_rate)
    return HealthAssessment(state, tuple(reasons), metrics)
