from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from trader_bot.ingestion import IngestionContractError, ingest_series
from trader_bot.ingestion_cycle import SeriesPlan, run_cycle
from trader_bot.ingestion_store import IngestionStore
from trader_bot.models import DataRequest, Instrument, MarketBar, OfferSide, Quote, Timeframe


class FakeProvider:
    def __init__(self, bars: list[MarketBar], *, fail_instrument: int | None = None) -> None:
        self._bars = bars
        self._fail_instrument = fail_instrument

    def instruments(self) -> list[Instrument]:
        return []

    def historical_bars(self, request: DataRequest) -> list[MarketBar]:
        if request.instrument == self._fail_instrument:
            raise RuntimeError("provider unavailable for this series")
        return [bar for bar in self._bars if bar.instrument == request.instrument and bar.offer_side is request.offer_side]

    def current_quotes(self, instruments: list[int]) -> list[Quote]:
        return []

    def health_check(self) -> bool:
        return True


def _bar(instrument: int, timestamp: datetime, side: OfferSide = OfferSide.BID) -> MarketBar:
    return MarketBar(
        timestamp=timestamp,
        instrument=instrument,
        timeframe=Timeframe.ONE_MINUTE,
        offer_side=side,
        open=Decimal("1.0"),
        high=Decimal("1.2"),
        low=Decimal("0.9"),
        close=Decimal("1.1"),
        volume=Decimal("10"),
    )


def test_ingestion_is_idempotent_and_checkpoints(tmp_path: Path) -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=3)
    bars = [_bar(1, start), _bar(1, start + timedelta(minutes=1))]
    provider = FakeProvider(bars)
    with IngestionStore(tmp_path / "ingestion.duckdb") as store:
        first = ingest_series(
            provider,
            store,
            provider_name="fake",
            asset_class="FOREX",
            instrument=1,
            timeframe=Timeframe.ONE_MINUTE,
            offer_side=OfferSide.BID,
            start=start,
            end=end,
            observed_at=end,
        )
        second = ingest_series(
            provider,
            store,
            provider_name="fake",
            asset_class="FOREX",
            instrument=1,
            timeframe=Timeframe.ONE_MINUTE,
            offer_side=OfferSide.BID,
            start=start,
            end=end,
            observed_at=end,
        )
        assert first.received == 2
        assert first.stored == 2
        assert second.received == 2
        assert second.stored == 0
        assert store.count_series(
            provider="fake",
            asset_class="FOREX",
            instrument=1,
            timeframe=Timeframe.ONE_MINUTE.value,
            offer_side=OfferSide.BID.value,
        ) == 2
        checkpoint = store.checkpoint(
            provider="fake",
            asset_class="FOREX",
            instrument=1,
            timeframe=Timeframe.ONE_MINUTE.value,
            offer_side=OfferSide.BID.value,
        )
        assert checkpoint is not None
        assert checkpoint["as_of"] == start + timedelta(minutes=1)


def test_cycle_isolates_series_failures(tmp_path: Path) -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    now = start + timedelta(minutes=3)
    plans = (
        SeriesPlan("FOREX", 1, Timeframe.ONE_MINUTE, OfferSide.BID, start),
        SeriesPlan("FOREX", 2, Timeframe.ONE_MINUTE, OfferSide.BID, start),
    )
    provider = FakeProvider([_bar(1, start)], fail_instrument=2)
    with IngestionStore(tmp_path / "cycle.duckdb") as store:
        outcomes = run_cycle(provider, store, provider_name="fake", plans=plans, now=now)
    assert [outcome.status for outcome in outcomes] == ["UPDATED", "FAILED"]
    assert outcomes[1].reason is not None
    assert "provider unavailable" in outcomes[1].reason


def test_invalid_provider_response_fails_closed() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    request = DataRequest(
        instrument=1,
        timeframe=Timeframe.ONE_MINUTE,
        start=start,
        end=start + timedelta(minutes=1),
        offer_side=OfferSide.BID,
    )
    wrong = _bar(2, start)
    try:
        from trader_bot.ingestion import validate_provider_bars
        validate_provider_bars([wrong], request=request)
    except IngestionContractError as exc:
        assert "unexpected instrument" in str(exc)
    else:
        raise AssertionError("invalid provider response was accepted")
