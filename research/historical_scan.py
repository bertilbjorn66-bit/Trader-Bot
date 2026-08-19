from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

from trader_bot.data_provider import MarketDataProvider
from trader_bot.models import DataRequest, MarketBar, OfferSide, Timeframe


def iter_bid_ask_batches(
    provider: MarketDataProvider,
    instrument: int,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    max_days_per_batch: int = 7,
) -> Iterator[tuple[tuple[MarketBar, ...], tuple[MarketBar, ...]]]:
    """Stream bounded BID/ASK historical windows without building a raw archive."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start >= end:
        raise ValueError("start must be before end")
    if max_days_per_batch <= 0:
        raise ValueError("max_days_per_batch must be positive")

    cursor = start
    while cursor < end:
        batch_end = min(end, cursor + timedelta(days=max_days_per_batch))
        bid = tuple(
            provider.historical_bars(
                DataRequest(
                    instrument=instrument,
                    timeframe=timeframe,
                    start=cursor,
                    end=batch_end,
                    offer_side=OfferSide.BID,
                )
            )
        )
        ask = tuple(
            provider.historical_bars(
                DataRequest(
                    instrument=instrument,
                    timeframe=timeframe,
                    start=cursor,
                    end=batch_end,
                    offer_side=OfferSide.ASK,
                )
            )
        )
        bid_by_time = {bar.timestamp: bar for bar in bid}
        ask_by_time = {bar.timestamp: bar for bar in ask}
        if set(bid_by_time) != set(ask_by_time):
            missing_ask = len(set(bid_by_time) - set(ask_by_time))
            missing_bid = len(set(ask_by_time) - set(bid_by_time))
            raise ValueError(
                f"BID/ASK timestamp mismatch: missing_ask={missing_ask}, missing_bid={missing_bid}"
            )
        yield (
            tuple(bid_by_time[timestamp] for timestamp in sorted(bid_by_time)),
            tuple(ask_by_time[timestamp] for timestamp in sorted(ask_by_time)),
        )
        cursor = batch_end
