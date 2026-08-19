from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TimeSplit:
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime


def validate_split(split: TimeSplit) -> None:
    points = (
        split.train_start,
        split.train_end,
        split.validation_start,
        split.validation_end,
        split.test_start,
        split.test_end,
    )
    if any(p.tzinfo is None for p in points):
        raise ValueError("All validation boundaries must be timezone-aware")
    if not all(a < b for a, b in zip(points, points[1:])):
        raise ValueError("Walk-forward split boundaries must be strictly increasing")


def can_use_observation(observation_time: datetime, feature_time: datetime, outcome_end: datetime) -> bool:
    """Prevent target leakage: training evidence cannot use an outcome not yet known."""
    if observation_time.tzinfo is None or feature_time.tzinfo is None or outcome_end.tzinfo is None:
        raise ValueError("Times must be timezone-aware")
    return feature_time < observation_time and outcome_end <= observation_time
