from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OfferSide(StrEnum):
    BID = "B"
    ASK = "A"


class Timeframe(StrEnum):
    TEN_SECONDS = "10sec"
    ONE_MINUTE = "1min"
    FIVE_MINUTES = "5min"  # derived locally from 1-minute candles
    TEN_MINUTES = "10m"
    FIFTEEN_MINUTES = "15min"  # derived locally from 1-minute candles
    ONE_HOUR = "1hour"
    FOUR_HOURS = "4hour"  # derived locally from 1-hour candles
    ONE_DAY = "1day"
    ONE_DAY_EET = "1day_eet"
    TICK = "tick"


PROVIDER_TIMEFRAMES = {
    Timeframe.TEN_SECONDS,
    Timeframe.ONE_MINUTE,
    Timeframe.TEN_MINUTES,
    Timeframe.ONE_HOUR,
    Timeframe.ONE_DAY,
    Timeframe.ONE_DAY_EET,
    Timeframe.TICK,
}


class MarketBar(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    instrument: int
    timeframe: Timeframe
    offer_side: OfferSide
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None

    @model_validator(mode="after")
    def validate_ohlc(self) -> "MarketBar":
        if self.high < max(self.open, self.close):
            raise ValueError("high must be >= open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be <= open and close")
        if self.low > self.high:
            raise ValueError("low must be <= high")
        return self


class DataRequest(BaseModel):
    instrument: int = Field(gt=0)
    timeframe: Timeframe
    start: datetime
    end: datetime
    offer_side: OfferSide

    @model_validator(mode="after")
    def validate_range(self) -> "DataRequest":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("start must be before end")
        if self.timeframe not in PROVIDER_TIMEFRAMES:
            raise ValueError("Derived timeframes must be constructed locally, not requested from the provider")
        return self


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    instrument: int
    bid: Decimal
    ask: Decimal

    @model_validator(mode="after")
    def validate_quote(self) -> "Quote":
        if self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        return self
