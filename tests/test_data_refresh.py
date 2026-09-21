from datetime import datetime, timedelta, timezone

from research.data_freshness import FeedSnapshot, default_feed_contracts
from research.data_refresh import plan_refresh
from trader_bot.asset_universe import AssetClass


def _snapshot(asset_class: AssetClass) -> FeedSnapshot:
    contract = default_feed_contracts()[asset_class]
    as_of = datetime(2026, 8, 29, 6, 0, tzinfo=timezone.utc)
    return FeedSnapshot(
        asset_class=asset_class,
        instrument="TEST",
        provider=contract.provider,
        as_of=as_of,
        observed_at=as_of,
        fields=contract.required_fields,
        source_hash="refresh-test",
    )


def test_fx_refresh_requests_both_executable_sides() -> None:
    contract = default_feed_contracts()[AssetClass.FOREX]
    now = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
    requests = plan_refresh(_snapshot(AssetClass.FOREX), contract, instrument_id=7, now=now)
    assert {request.offer_side.value for request in requests} == {"B", "A"}
    assert {request.timeframe.value for request in requests} == {"1min", "1hour", "1day"}
    assert all(request.provider == "Dukascopy" for request in requests)


def test_crypto_refresh_requests_only_trade_candle_side() -> None:
    contract = default_feed_contracts()[AssetClass.CRYPTO]
    now = datetime(2026, 8, 29, 6, 30, tzinfo=timezone.utc)
    requests = plan_refresh(_snapshot(AssetClass.CRYPTO), contract, instrument_id=9, now=now)
    assert {request.offer_side.value for request in requests} == {"B"}
    assert {request.timeframe.value for request in requests} == {"1sec", "1min", "1hour", "1day"}
    assert all(request.provider == "Binance" for request in requests)


def test_current_snapshot_creates_no_refresh_requests() -> None:
    contract = default_feed_contracts()[AssetClass.EQUITY]
    as_of = datetime(2026, 8, 29, 7, 59, tzinfo=timezone.utc)
    snapshot = FeedSnapshot(
        asset_class=AssetClass.EQUITY,
        instrument="NVDA",
        provider="Stooq",
        as_of=as_of,
        observed_at=as_of,
        fields=contract.required_fields,
        source_hash="current-test",
    )
    now = as_of + timedelta(seconds=30)
    assert plan_refresh(snapshot, contract, instrument_id=11, now=now) == ()
