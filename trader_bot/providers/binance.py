from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..data_provider import ProviderProtocolError, ProviderRateLimited, ProviderUnavailable
from ..models import DataRequest, Instrument, MarketBar, OfferSide, Quote, Timeframe


class BinanceProvider:
    """Public Binance Spot market-data adapter; never handles account credentials."""

    BASE_URL = "https://api.binance.com"
    KLINES_PATH = "/api/v3/klines"
    TICKER_PATH = "/api/v3/ticker/bookTicker"

    def __init__(
        self,
        symbol_by_instrument: Mapping[int, str],
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not symbol_by_instrument:
            raise ValueError("at least one Binance instrument mapping is required")
        normalized = {int(key): str(value).upper().strip() for key, value in symbol_by_instrument.items()}
        if any(not value for value in normalized.values()):
            raise ValueError("Binance symbols must be non-empty")
        self._symbols = normalized
        self._ids_by_symbol = {value: key for key, value in normalized.items()}
        self._client = client or httpx.Client(base_url=self.BASE_URL, timeout=30.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BinanceProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((ProviderUnavailable, ProviderRateLimited)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        if response.status_code == 429:
            raise ProviderRateLimited("Binance rate limit reached")
        if response.status_code >= 500:
            raise ProviderUnavailable(f"Binance server error: {response.status_code}")
        if response.status_code >= 400:
            raise ProviderProtocolError(f"Binance HTTP error: {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderProtocolError("Binance returned invalid JSON") from exc

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ProviderProtocolError(f"Invalid numeric value: {value!r}") from exc

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ProviderProtocolError(f"Invalid timestamp: {value!r}") from exc

    @staticmethod
    def _interval(timeframe: Timeframe) -> str:
        mapping = {
            Timeframe.ONE_MINUTE: "1m",
            Timeframe.TEN_MINUTES: "10m",
            Timeframe.ONE_HOUR: "1h",
            Timeframe.FOUR_HOURS: "4h",
            Timeframe.ONE_DAY: "1d",
        }
        try:
            return mapping[timeframe]
        except KeyError as exc:
            raise ValueError("Binance provider currently supports minute/hour/day candle intervals") from exc

    def instruments(self) -> Sequence[Instrument]:
        return [Instrument(id=instrument_id, name=symbol, name_long=symbol) for instrument_id, symbol in sorted(self._symbols.items())]

    def historical_bars(self, request: DataRequest) -> Sequence[MarketBar]:
        if request.offer_side is not OfferSide.BID:
            raise ValueError("Binance Spot klines are not bid/ask-side candles")
        symbol = self._symbols.get(request.instrument)
        if symbol is None:
            raise KeyError(f"Unknown Binance instrument id: {request.instrument}")
        interval = self._interval(request.timeframe)
        payload = self._get(
            self.KLINES_PATH,
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": int(request.start.timestamp() * 1000),
                "endTime": int(request.end.timestamp() * 1000),
                "limit": 1000,
            },
        )
        if not isinstance(payload, list):
            raise ProviderProtocolError("Expected Binance klines response to be a JSON array")
        bars: list[MarketBar] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                raise ProviderProtocolError("Malformed Binance kline row")
            bars.append(
                MarketBar(
                    timestamp=self._timestamp(row[0]),
                    instrument=request.instrument,
                    timeframe=request.timeframe,
                    offer_side=request.offer_side,
                    open=self._decimal(row[1]),
                    high=self._decimal(row[2]),
                    low=self._decimal(row[3]),
                    close=self._decimal(row[4]),
                    volume=self._decimal(row[5]),
                )
            )
        return [bar for bar in bars if request.start <= bar.timestamp < request.end]

    def current_quotes(self, instruments: Sequence[int]) -> Sequence[Quote]:
        quotes: list[Quote] = []
        for instrument_id in instruments:
            symbol = self._symbols.get(instrument_id)
            if symbol is None:
                raise KeyError(f"Unknown Binance instrument id: {instrument_id}")
            payload = self._get(self.TICKER_PATH, {"symbol": symbol})
            if not isinstance(payload, dict):
                raise ProviderProtocolError("Expected Binance book-ticker response to be an object")
            if str(payload.get("symbol", "")).upper() != symbol:
                raise ProviderProtocolError("Binance response symbol does not match requested instrument")
            quotes.append(
                Quote(
                    timestamp=datetime.now(timezone.utc),
                    instrument=instrument_id,
                    bid=self._decimal(payload["bidPrice"]),
                    ask=self._decimal(payload["askPrice"]),
                )
            )
        return quotes

    def health_check(self) -> bool:
        try:
            payload = self._get("/api/v3/ping", {})
            return payload == {}
        except Exception:
            return False
