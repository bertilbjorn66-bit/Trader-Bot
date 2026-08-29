from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum


class DataHealth(StrEnum):
    FRESH = "FRESH"
    WATCH = "WATCH"
    STALE = "STALE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    """Domain-specific refresh policy without embedding provider behavior."""

    interval: timedelta
    grace: timedelta
    max_backfill: timedelta


@dataclass(frozen=True, slots=True)
class SeriesHealth:
    """Auditable state for one provider/asset/instrument/timeframe/side series."""

    health: DataHealth
    age: timedelta | None
    reason: str
    refresh_due: bool
    blocked: bool


POLICIES: dict[str, RefreshPolicy] = {
    "FOREX": RefreshPolicy(timedelta(minutes=5), timedelta(minutes=10), timedelta(days=7)),
    "CRYPTO": RefreshPolicy(timedelta(minutes=1), timedelta(minutes=3), timedelta(days=3)),
    "METAL": RefreshPolicy(timedelta(minutes=5), timedelta(minutes=15), timedelta(days=7)),
    "METALS": RefreshPolicy(timedelta(minutes=5), timedelta(minutes=15), timedelta(days=7)),
    "ENERGY": RefreshPolicy(timedelta(minutes=5), timedelta(minutes=15), timedelta(days=7)),
    "COMMODITY": RefreshPolicy(timedelta(hours=1), timedelta(hours=2), timedelta(days=31)),
    "EQUITY": RefreshPolicy(timedelta(days=1), timedelta(days=2), timedelta(days=370)),
    "INDEX": RefreshPolicy(timedelta(days=1), timedelta(days=2), timedelta(days=370)),
}


def policy_for(asset_class: str) -> RefreshPolicy:
    key = asset_class.strip().upper()
    try:
        return POLICIES[key]
    except KeyError as exc:
        raise ValueError(f"no refresh policy registered for asset class: {asset_class!r}") from exc


def assess_health(
    *,
    asset_class: str,
    latest_timestamp: datetime | None,
    now: datetime,
    source_valid: bool,
    contiguous: bool,
) -> SeriesHealth:
    """Fail closed when source validation or time-series continuity is not trustworthy."""

    now_utc = now.astimezone(timezone.utc)
    if latest_timestamp is None:
        return SeriesHealth(DataHealth.BLOCKED, None, "missing_latest_timestamp", True, True)
    if latest_timestamp.tzinfo is None:
        raise ValueError("latest_timestamp must be timezone-aware")

    latest_utc = latest_timestamp.astimezone(timezone.utc)
    age = now_utc - latest_utc
    if age < timedelta(0):
        return SeriesHealth(DataHealth.BLOCKED, age, "latest_timestamp_in_future", False, True)
    if not source_valid:
        return SeriesHealth(DataHealth.BLOCKED, age, "source_validation_failed", True, True)
    if not contiguous:
        return SeriesHealth(DataHealth.BLOCKED, age, "series_not_contiguous", True, True)

    policy = policy_for(asset_class)
    if age <= policy.interval:
        return SeriesHealth(DataHealth.FRESH, age, "within_refresh_interval", False, False)
    if age <= policy.interval + policy.grace:
        return SeriesHealth(DataHealth.WATCH, age, "inside_grace_window", True, False)
    return SeriesHealth(DataHealth.STALE, age, "refresh_overdue", True, False)


def refresh_window(
    *,
    asset_class: str,
    latest_timestamp: datetime | None,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Return a bounded incremental refresh window and never exceed domain backfill limits."""

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    policy = policy_for(asset_class)
    end = now.astimezone(timezone.utc)
    if latest_timestamp is None:
        start = end - policy.max_backfill
    else:
        if latest_timestamp.tzinfo is None:
            raise ValueError("latest_timestamp must be timezone-aware")
        start = max(
            latest_timestamp.astimezone(timezone.utc),
            end - policy.max_backfill,
        )
    if start >= end:
        return end, end
    return start, end
