from datetime import datetime, timedelta, timezone
from decimal import Decimal

from trader_bot.aggregation import aggregate_bars
from trader_bot.models import MarketBar, OfferSide, Timeframe


def make_bar(ts, i):
    p = Decimal(i + 1)
    return MarketBar(
        timestamp=ts,
        instrument=1,
        timeframe=Timeframe.ONE_MINUTE,
        offer_side=OfferSide.BID,
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
    assert len(result) == 1
    assert result[0].timeframe == Timeframe.FIVE_MINUTES
    assert result[0].open == Decimal("1")
    assert result[0].close == Decimal("5.25")


def test_partial_bucket_is_rejected():
    start = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    bars = [make_bar(start + timedelta(minutes=i), i) for i in range(4)]
    assert aggregate_bars(bars, Timeframe.FIVE_MINUTES) == []
