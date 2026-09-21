from datetime import datetime, timedelta, timezone

import pytest

from research.data_freshness import (
    DataFeedContract,
    FeedSnapshot,
    FreshnessState,
    assess_freshness,
    default_feed_contracts,
    refresh_window,
)
from trader_bot.asset_universe import AssetClass
from trader_bot.models import Timeframe


def snapshot(contract: DataFeedContract, *, age: timedelta = timedelta(minutes=5)) -> FeedSnapshot:
    now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
    as_of = now - age
    return FeedSnapshot(
        asset_class=contract.asset_class,
        instrument="TEST",
        provider=contract.provider,
        as_of=as_of,
        observed_at=as_of,
        fields=contract.required_fields,
        source_hash="abc123",
    )


def test_current_data_does_not_refresh():
    contract = default_feed_contracts()[AssetClass.CRYPTO]
    now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
    snap = snapshot(contract, age=timedelta(minutes=1))
    assert assess_freshness(snap, contract, now=now) is FreshnessState.CURRENT
    assert refresh_window(snap, contract, now=now) is None


def test_due_data_requests_only_incremental_window():
    contract = default_feed_contracts()[AssetClass.CRYPTO]
    now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
    snap = snapshot(contract, age=timedelta(minutes=20))
    assert assess_freshness(snap, contract, now=now) is FreshnessState.DUE
    assert refresh_window(snap, contract, now=now) == (snap.as_of, now)


def test_stale_data_is_not_silently_accepted():
    contract = default_feed_contracts()[AssetClass.FOREX]
    now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
    snap = snapshot(contract, age=timedelta(hours=7))
    assert assess_freshness(snap, contract, now=now) is FreshnessState.STALE


def test_unknown_snapshot_cannot_be_refreshed_without_baseline():
    contract = default_feed_contracts()[AssetClass.METAL]
    now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
    assert assess_freshness(None, contract, now=now) is FreshnessState.UNKNOWN
    assert refresh_window(None, contract, now=now) is None


def test_future_as_of_is_unknown():
    contract = default_feed_contracts()[AssetClass.EQUITY]
    now = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
    snap = snapshot(contract, age=timedelta(days=-1))
    assert assess_freshness(snap, contract, now=now) is FreshnessState.UNKNOWN


def test_contract_rejects_placeholder_provider():
    contract = DataFeedContract(
        asset_class=AssetClass.COMMODITY,
        provider="provider_pending",
        required_timeframes=(Timeframe.ONE_DAY,),
        required_fields=("timestamp", "close"),
        refresh_interval=timedelta(days=1),
        maximum_staleness=timedelta(days=2),
    )
    with pytest.raises(ValueError, match="concrete data provider"):
        contract.validate()
