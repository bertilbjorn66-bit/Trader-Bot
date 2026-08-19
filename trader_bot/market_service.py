from __future__ import annotations

from datetime import datetime
from collections.abc import Sequence

from .data_provider import MarketDataProvider
from .integrity import validate_bid_ask_alignment, validate_bars
from .models import DataRequest, MarketBar, OfferSide, Timeframe


class MarketDataService:
    """Application-level data service with provider and integrity boundaries."""

    def __init__(self, provider: MarketDataProvider) -> None:
        self.provider = provider

    def resolve_instrument_id(self, symbol: str) -> int:
        normalized = symbol.replace("/", "").replace("_", "").upper()
        for instrument in self.provider.instruments():  # type: ignore[attr-defined]
            if instrument.name.replace("/", "").replace("_", "").upper() == normalized:
                return instrument.id
        raise ValueError(f"Instrument not found: {symbol}")

    def historical_bid_ask(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Sequence[MarketBar], Sequence[MarketBar]]:
        instrument = self.resolve_instrument_id(symbol)
        bid = self.provider.historical_bars(
            DataRequest(
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end,
                offer_side=OfferSide.BID,
            )
        )
        ask = self.provider.historical_bars(
            DataRequest(
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end,
                offer_side=OfferSide.ASK,
            )
        )

        bid_report = validate_bars(bid)
        ask_report = validate_bars(ask)
        if not bid_report.ok or not ask_report.ok:
            raise ValueError("Market data failed integrity validation")
        validate_bid_ask_alignment(bid, ask)
        return bid, ask
