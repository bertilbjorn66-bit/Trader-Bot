from __future__ import annotations

from datetime import datetime, timedelta

from .types import State, ValidationFold


def ensure_time_order(states: list[State]) -> None:
    previous: datetime | None = None
    for state in states:
        if previous is not None and state.timestamp <= previous:
            raise ValueError("States must be strictly increasing")
        previous = state.timestamp


def no_future_features(state: State, allowed_at: datetime) -> None:
    if state.timestamp > allowed_at:
        raise ValueError("State timestamp is after its decision time")


def expanding_walk_forward(
    timestamps: list[datetime],
    initial_train: timedelta,
    test_window: timedelta,
    step: timedelta | None = None,
    purge: timedelta = timedelta(0),
) -> list[ValidationFold]:
    if initial_train <= timedelta(0):
        raise ValueError("initial_train must be positive")
    if test_window <= timedelta(0):
        raise ValueError("test_window must be positive")
    if purge < timedelta(0):
        raise ValueError("purge cannot be negative")
    if not timestamps:
        return []
    if any(ts.tzinfo is None for ts in timestamps):
        raise ValueError("All timestamps must be timezone-aware")
    ordered = sorted(set(timestamps))
    start = ordered[0]
    train_end = start + initial_train
    step = step or test_window
    if step <= timedelta(0):
        raise ValueError("step must be positive")
    folds: list[ValidationFold] = []
    while train_end + purge + test_window <= ordered[-1]:
        test_start = train_end + purge
        test_end = test_start + test_window
        folds.append(ValidationFold(start, train_end, test_start, test_end))
        train_end += step
    return folds


def purge_overlaps(states: list[State], cutoff: datetime) -> list[State]:
    return [s for s in states if s.timestamp < cutoff]
