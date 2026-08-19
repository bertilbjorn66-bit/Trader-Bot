from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.aggregation import aggregate_bars, aggregate_series
from trader_bot.models import MarketBar, OfferSide, Timeframe
from trader_bot.validation import validate_bar_sequence


def make_bar(ts, i, *, instrument=1, timeframe=Timeframe.ONE_MINUTE, side=OfferSide.BID):
    p = Decimal(i + 1)
    return MarketBar(
        timestamp=ts,
        instrument=instrument,
        timeframe=timeframe,
        offer_side=side,
        open=p,
        high=p + Decimal("0.5"),
        low=p - Decimal("0.5"),
        close=p + Decimal("0.25"),
        volume=Decimal("1"),
    )


def test_five_minute_aggregation_is_complete_and_labeled():
    start = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    bars = [make_bar(start + timedelta(minutes=i), i) for i in range(5)]
    result = aggregate_bars(bars, Timeframe.FIVE_MINUTES)
    assert result.timeframe == Timeframe.FIVE_MINUTES
    assert result.open == Decimal("1")
    assert result.close == Decimal("5.25")


def test_partial_bucket_is_rejected():
    start = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    bars = [make_bar(start + timedelta(minutes=i), i) for i in range(4)]
    with pytest.raises(ValueError, match="group length"):
        aggregate_bars(bars, Timeframe.FIVE_MINUTES)


def test_series_skips_unaligned_prefix_and_aggregates_boundary_bucket():
    start = datetime(2026, 1, 5, 10, 1, tzinfo=timezone.utc)
    bars = [make_bar(start + timedelta(minutes=i), i) for i in range(9)]
    result = aggregate_series(bars, Timeframe.FIVE_MINUTES)
    assert len(result) == 1
    assert result[0].timestamp == datetime(2026, 1, 5, 10, 5, tzinfo=timezone.utc)


def test_sequence_validation_rejects_duplicates_and_identity_mismatches():
    start = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    duplicate = [make_bar(start, 0), make_bar(start, 1)]
    with pytest.raises(ValueError, match="strictly increasing"):
        validate_bar_sequence(duplicate)

    mismatch = [make_bar(start, 0), make_bar(start + timedelta(minutes=1), 1, instrument=2)]
    with pytest.raises(ValueError, match="consistent instrument"):
        validate_bar_sequence(mismatch)
