from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trader_bot.asset_universe import AssetClass
from trader_bot.models import DataRequest, OfferSide, Timeframe

from .data_freshness import (
    DataFeedContract,
    FeedSnapshot,
    FreshnessState,
    assess_freshness,
    refresh_window,
)


@dataclass(frozen=True, slots=True)
class RefreshRequest:
    asset_class: AssetClass
    instrument_id: int
    timeframe: Timeframe
    start: datetime
    end: datetime
    offer_side: OfferSide
    provider: str

    def to_data_request(self) -> DataRequest:
        return DataRequest(
            instrument=self.instrument_id,
            timeframe=self.timeframe,
            start=self.start,
            end=self.end,
            offer_side=self.offer_side,
        )


def plan_refresh(
    snapshot: FeedSnapshot | None,
    contract: DataFeedContract,
    *,
    instrument_id: int,
    offer_side: OfferSide = OfferSide.BID,
    now: datetime | None = None,
) -> tuple[RefreshRequest, ...]:
    window = refresh_window(snapshot, contract, now=now)
    if window is None:
        return ()
    start, end = window
    return tuple(
        RefreshRequest(
            asset_class=contract.asset_class,
            instrument_id=instrument_id,
            timeframe=timeframe,
            start=start,
            end=end,
            offer_side=offer_side,
            provider=contract.provider,
        )
        for timeframe in contract.required_timeframes
    )


def require_fresh_data(
    snapshot: FeedSnapshot | None,
    contract: DataFeedContract,
    *,
    now: datetime | None = None,
) -> FreshnessState:
    return assess_freshness(snapshot, contract, now=now)
