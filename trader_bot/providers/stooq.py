from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..data_provider import ProviderProtocolError, ProviderRateLimited, ProviderUnavailable
from ..models import DataRequest, Instrument, MarketBar, OfferSide, Quote, Timeframe


class StooqProvider:
    """Public Stooq end-of-day adapter for equities and indices."""

    BASE_URL = "https://stooq.com/q/d/l/"

    def __init__(
        self,
        symbol_by_instrument: Mapping[int, str],
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not symbol_by_instrument:
            raise ValueError("at least one Stooq instrument mapping is required")
        normalized = {int(key): str(value).lower().strip() for key, value in symbol_by_instrument.items()}
        if any(not value for value in normalized.values()):
            raise ValueError("Stooq symbols must be non-empty")
        self._symbols = normalized
        self._client = client or httpx.Client(timeout=30.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> StooqProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((ProviderUnavailable, ProviderRateLimited)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        reraise=True,
    )
    def _get_csv(self, symbol: str) -> str:
        try:
            response = self._client.get(self.BASE_URL, params={"s": symbol, "i": "d"})
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        if response.status_code == 429:
            raise ProviderRateLimited("Stooq rate limit reached")
        if response.status_code >= 500:
            raise ProviderUnavailable(f"Stooq server error: {response.status_code}")
        if response.status_code >= 400:
            raise ProviderProtocolError(f"Stooq HTTP error: {response.status_code}")
        return response.text

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ProviderProtocolError(f"Invalid Stooq numeric value: {value!r}") from exc

    def instruments(self) -> Sequence[Instrument]:
        return [Instrument(id=instrument_id, name=symbol, name_long=symbol) for instrument_id, symbol in sorted(self._symbols.items())]

    def historical_bars(self, request: DataRequest) -> Sequence[MarketBar]:
        if request.offer_side is not OfferSide.BID:
            raise ValueError("Stooq daily data does not provide separate bid/ask candles")
        if request.timeframe is not Timeframe.ONE_DAY:
            raise ValueError("StooqProvider only supports daily bars")
        symbol = self._symbols.get(request.instrument)
        if symbol is None:
            raise KeyError(f"Unknown Stooq instrument id: {request.instrument}")
        csv_text = self._get_csv(symbol)
        rows = csv.DictReader(io.StringIO(csv_text))
        bars: list[MarketBar] = []
        for row in rows:
            try:
                timestamp = datetime.strptime(row["Date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                bars.append(
                    MarketBar(
                        timestamp=timestamp,
                        instrument=request.instrument,
                        timeframe=request.timeframe,
                        offer_side=request.offer_side,
                        open=self._decimal(row["Open"]),
                        high=self._decimal(row["High"]),
                        low=self._decimal(row["Low"]),
                        close=self._decimal(row["Close"]),
                        volume=self._decimal(row["Volume"]) if row.get("Volume") not in {None, "", "-"} else None,
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise ProviderProtocolError("Malformed Stooq CSV row") from exc
        return [bar for bar in bars if request.start <= bar.timestamp < request.end]

    def current_quotes(self, instruments: Sequence[int]) -> Sequence[Quote]:
        raise NotImplementedError("Stooq daily research adapter does not provide current executable quotes")

    def health_check(self) -> bool:
        try:
            response = self._client.get(self.BASE_URL, params={"s": next(iter(self._symbols.values())), "i": "d"})
        except httpx.HTTPError:
            return False
        return response.status_code == 200
