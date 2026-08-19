from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.context import build_state
from trader_bot.decision import Action, decide
from trader_bot.integrity import validate_bars, validate_bid_ask_alignment
from trader_bot.models import DataRequest, MarketBar, OfferSide, Timeframe
from trader_bot.risk import OutcomeSummary, RiskLimits
from trader_bot.safety import SafetyState, authorize_live_action
from trader_bot.validation import TimeSplit, validate_split


def bar(ts, side, close):
    price = Decimal(str(close))
    return MarketBar(
        timestamp=ts,
        instrument=1,
        timeframe=Timeframe.ONE_MINUTE,
        offer_side=side,
        open=price,
        high=price,
        low=price,
        close=price,
    )


def test_data_request_requires_timezone_aware_times():
    with pytest.raises(ValueError):
        DataRequest(
            instrument=1,
            timeframe=Timeframe.ONE_MINUTE,
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 2, tzinfo=timezone.utc),
            offer_side=OfferSide.BID,
        )


def test_bid_ask_alignment_rejects_mismatch():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        validate_bid_ask_alignment(
            [bar(ts, OfferSide.BID, 1)],
            [bar(ts + timedelta(minutes=1), OfferSide.ASK, 1)],
        )


def test_integrity_rejects_duplicate_timestamps():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    report = validate_bars([bar(ts, OfferSide.BID, 1), bar(ts, OfferSide.BID, 1)])
    assert report.duplicate_timestamps == 1
    assert not report.ok


def test_context_requires_enough_history():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bid = [bar(ts + timedelta(minutes=i), OfferSide.BID, 1 + i / 10000) for i in range(60)]
    ask = [bar(ts + timedelta(minutes=i), OfferSide.ASK, 1.0001 + i / 10000) for i in range(60)]
    with pytest.raises(ValueError):
        build_state(bid, ask)


def test_live_execution_is_default_denied():
    summary = OutcomeSummary(500, 0.7, 0.3, 0.2, 0.4, -0.3, 0.8, 1.2)
    decision = decide(summary, Action.BUY, RiskLimits())
    state = SafetyState()
    assert authorize_live_action(decision, state) == Action.NO_TRADE


def test_walk_forward_boundaries_are_strict():
    t = datetime(2020, 1, 1, tzinfo=timezone.utc)
    split = TimeSplit(
        t,
        t + timedelta(days=1),
        t + timedelta(days=2),
        t + timedelta(days=3),
        t + timedelta(days=4),
        t + timedelta(days=5),
    )
    validate_split(split)
