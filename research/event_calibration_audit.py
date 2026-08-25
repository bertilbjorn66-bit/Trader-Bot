from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Sequence

from research.intelligence_controls import CalibrationReport, calibration_report


@dataclass(frozen=True)
class EventRelease:
    event_id: str
    event_type: str
    release_at: int
    known_at: int
    revision: int

    def validate(self) -> None:
        if self.known_at > self.release_at:
            raise ValueError("event cannot be known after release")
        if self.revision < 0:
            raise ValueError("revision must be non-negative")


@dataclass(frozen=True)
class LogisticCalibrationModel:
    intercept: float
    slope: float
    training_observations: int

    def probability(self, score: float) -> float:
        z = self.intercept + self.slope * score
        if z >= 0:
            return 1.0 / (1.0 + exp(-z))
        ez = exp(z)
        return ez / (1.0 + ez)

    def predict_many(self, scores: Sequence[float]) -> list[float]:
        return [self.probability(score) for score in scores]


@dataclass(frozen=True)
class CalibrationFit:
    model: LogisticCalibrationModel
    training_report: CalibrationReport


def fit_logistic_calibrator(
    scores: Sequence[float],
    outcomes: Sequence[int],
    steps: int = 1200,
    learning_rate: float = 0.05,
) -> CalibrationFit:
    if len(scores) != len(outcomes) or len(scores) < 20:
        raise ValueError("calibration requires aligned samples of at least 20 observations")
    if any(outcome not in (0, 1) for outcome in outcomes):
        raise ValueError("outcomes must be binary")
    if steps <= 0 or learning_rate <= 0:
        raise ValueError("invalid optimizer parameters")
    intercept = 0.0
    slope = 0.0
    n = float(len(scores))
    for _ in range(steps):
        probabilities = []
        for score in scores:
            z = intercept + slope * score
            probabilities.append(1.0 / (1.0 + exp(-z)) if z >= 0 else exp(z) / (1.0 + exp(z)))
        grad_intercept = sum(probability - outcome for probability, outcome in zip(probabilities, outcomes)) / n
        grad_slope = sum((probability - outcome) * score for probability, outcome, score in zip(probabilities, outcomes, scores)) / n
        intercept -= learning_rate * grad_intercept
        slope -= learning_rate * grad_slope
    model = LogisticCalibrationModel(intercept, slope, len(scores))
    report = calibration_report(model.predict_many(scores), outcomes)
    return CalibrationFit(model, report)


@dataclass(frozen=True)
class CalibrationValidation:
    training: CalibrationReport
    validation: CalibrationReport
    training_observations: int
    validation_observations: int
    information_leakage: bool


def validate_calibration(
    fit: CalibrationFit,
    validation_scores: Sequence[float],
    validation_outcomes: Sequence[int],
) -> CalibrationValidation:
    probabilities = fit.model.predict_many(validation_scores)
    report = calibration_report(probabilities, validation_outcomes)
    return CalibrationValidation(
        training=fit.training_report,
        validation=report,
        training_observations=fit.model.training_observations,
        validation_observations=len(validation_scores),
        information_leakage=False,
    )
