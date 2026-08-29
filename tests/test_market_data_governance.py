from datetime import datetime, timedelta, timezone

import pytest

from trader_bot.market_data_governance import (
    DataHealth,
    assess_health,
    policy_for,
    refresh_window,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def test_policies_are_domain_specific() -> None:
    assert policy_for("FOREX").interval < policy_for("EQUITY").interval
    assert policy_for("CRYPTO").interval < policy_for("COMMODITY").interval


def test_missing_series_is_blocked() -> None:
    state = assess_health(
        asset_class="CRYPTO",
        latest_timestamp=None,
        now=NOW,
        source_valid=True,
        contiguous=True,
    )
    assert state.health == DataHealth.BLOCKED
    assert state.blocked is True
    assert state.refresh_due is True


def test_invalid_source_or_gap_blocks_research() -> None:
    latest = NOW - timedelta(minutes=1)
    invalid_source = assess_health(
        asset_class="CRYPTO",
        latest_timestamp=latest,
        now=NOW,
        source_valid=False,
        contiguous=True,
    )
    gap = assess_health(
        asset_class="CRYPTO",
        latest_timestamp=latest,
        now=NOW,
        source_valid=True,
        contiguous=False,
    )
    assert invalid_source.health == DataHealth.BLOCKED
    assert gap.health == DataHealth.BLOCKED


def test_fresh_watch_and_stale_states() -> None:
    fresh = assess_health(
        asset_class="FOREX",
        latest_timestamp=NOW - timedelta(minutes=4),
        now=NOW,
        source_valid=True,
        contiguous=True,
    )
    watch = assess_health(
        asset_class="FOREX",
        latest_timestamp=NOW - timedelta(minutes=10),
        now=NOW,
        source_valid=True,
        contiguous=True,
    )
    stale = assess_health(
        asset_class="FOREX",
        latest_timestamp=NOW - timedelta(minutes=30),
        now=NOW,
        source_valid=True,
        contiguous=True,
    )
    assert fresh.health == DataHealth.FRESH
    assert fresh.refresh_due is False
    assert watch.health == DataHealth.WATCH
    assert watch.refresh_due is True
    assert stale.health == DataHealth.STALE
    assert stale.refresh_due is True


def test_future_timestamp_is_fail_closed() -> None:
    state = assess_health(
        asset_class="EQUITY",
        latest_timestamp=NOW + timedelta(seconds=1),
        now=NOW,
        source_valid=True,
        contiguous=True,
    )
    assert state.health == DataHealth.BLOCKED
    assert state.blocked is True


def test_refresh_window_is_bounded_and_incremental() -> None:
    start, end = refresh_window(
        asset_class="FOREX",
        latest_timestamp=NOW - timedelta(minutes=6),
        now=NOW,
    )
    assert end == NOW
    assert start == NOW - timedelta(minutes=6)

    cold_start, _ = refresh_window(asset_class="EQUITY", latest_timestamp=None, now=NOW)
    assert NOW - cold_start == policy_for("EQUITY").max_backfill


def test_unknown_domain_fails_closed() -> None:
    with pytest.raises(ValueError):
        policy_for("UNKNOWN")
