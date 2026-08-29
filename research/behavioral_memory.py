from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class BehavioralObservation:
    timestamp: int
    instrument: str
    regime: str
    features: Mapping[str, float]
    outcome: float


@dataclass(frozen=True, slots=True)
class ContextSummary:
    instrument: str
    regime: str
    observations: int
    expectancy: float
    win_rate: float
    profit_factor: float | None
    outcome_std: float
    positive_observations: int

    @property
    def signal_quality(self) -> float:
        if self.observations == 0:
            return 0.0
        consistency = self.positive_observations / self.observations
        risk_penalty = 1.0 / (1.0 + self.outcome_std) if self.outcome_std >= 0 else 0.0
        return max(0.0, min(1.0, 0.5 * consistency + 0.5 * risk_penalty))


def _std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def summarize_context(
    observations: Iterable[BehavioralObservation],
    *,
    instrument: str,
    regime: str,
) -> ContextSummary:
    values = [
        observation.outcome
        for observation in observations
        if observation.instrument == instrument and observation.regime == regime
    ]
    if not values:
        return ContextSummary(instrument, regime, 0, 0.0, 0.0, None, 0.0, 0)
    wins = [value for value in values if value > 0.0]
    losses = [-value for value in values if value < 0.0]
    gross_loss = sum(losses)
    return ContextSummary(
        instrument=instrument,
        regime=regime,
        observations=len(values),
        expectancy=mean(values),
        win_rate=len(wins) / len(values),
        profit_factor=sum(wins) / gross_loss if gross_loss else None,
        outcome_std=_std(values),
        positive_observations=len(wins),
    )


def chronological_memory(
    observations: Iterable[BehavioralObservation],
    *,
    cutoff_timestamp: int,
) -> tuple[BehavioralObservation, ...]:
    """Return only matured historical observations available before a decision."""

    return tuple(
        sorted(
            (observation for observation in observations if observation.timestamp < cutoff_timestamp),
            key=lambda observation: observation.timestamp,
        )
    )


def conditional_memory(
    observations: Iterable[BehavioralObservation],
    *,
    instrument: str,
    cutoff_timestamp: int,
    context: Mapping[str, float],
    tolerances: Mapping[str, float],
) -> tuple[BehavioralObservation, ...]:
    """Find historically comparable states without using post-cutoff observations."""

    if set(context) != set(tolerances):
        raise ValueError("context and tolerance keys must match")
    if any(value < 0.0 for value in tolerances.values()):
        raise ValueError("context tolerances cannot be negative")
    history = chronological_memory(observations, cutoff_timestamp=cutoff_timestamp)
    matches: list[BehavioralObservation] = []
    for observation in history:
        if observation.instrument != instrument:
            continue
        if all(
            feature in observation.features
            and abs(float(observation.features[feature]) - float(context[feature])) <= tolerance
            for feature, tolerance in tolerances.items()
        ):
            matches.append(observation)
    return tuple(matches)
