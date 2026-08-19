from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from ..config import Settings, get_settings
from ..data_provider import ProviderProtocolError, ProviderRateLimited, ProviderUnavailable
from ..models import DataRequest, Instrument, MarketBar, Quote, Timeframe


class DukascopyProvider:
    """Dukascopy REST adapter isolated behind the provider interface."""

    BASE_URL = "https://freeserv.dukascopy.com/2.0/"
    HISTORICAL_PATH = "api/historicalPrices"
    CURRENT_PATH = "api/currentPrices"
    HEALTH_PATH = "api/lastOneMinuteCandles"
    INSTRUMENTS_PATH = "api/instrumentList"

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(timeout=self.settings.request_timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> DukascopyProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((ProviderUnavailable, ProviderRateLimited)),
        stop=stop_after_attempt(8),
        wait=wait_random_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    def _request(self, path: str, params: dict[str, Any]) -> Any:
        query = {"path": path, **params}
        if self.settings.dukascopy_api_key:
            query["key"] = self.settings.dukascopy_api_key
        try:
            response = self._client.get(self.BASE_URL, params=query)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        if response.status_code == 429:
            raise ProviderRateLimited("Dukascopy rate limit reached; retrying with exponential backoff")
        if response.status_code >= 500:
            raise ProviderUnavailable(f"Dukascopy server error: {response.status_code}")
        if response.status_code >= 400:
            raise ProviderProtocolError(f"Dukascopy HTTP error: {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderProtocolError("Dukascopy returned invalid JSON") from exc

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
    def _source_interval(timeframe: Timeframe) -> timedelta:
        return {
            Timeframe.TEN_SECONDS: timedelta(seconds=10),
            Timeframe.ONE_MINUTE: timedelta(minutes=1),
            Timeframe.TEN_MINUTES: timedelta(minutes=10),
            Timeframe.ONE_HOUR: timedelta(hours=1),
            Timeframe.ONE_DAY: timedelta(days=1),
            Timeframe.ONE_DAY_EET: timedelta(days=1),
        }[timeframe]

    def instruments(self) -> Sequence[Instrument]:
        payload = self._request(self.INSTRUMENTS_PATH, {})
        if not isinstance(payload, list):
            raise ProviderProtocolError("Expected instrumentList response to be a JSON array")
        result: list[Instrument] = []
        for row in payload:
            if not isinstance(row, dict):
                raise ProviderProtocolError("Instrument row is not an object")
            try:
                result.append(
                    Instrument(
                        id=int(row["id"]),
                        name=str(row["name"]),
                        pip_value=self._decimal(row["pipValue"])
                        if row.get("pipValue") is not None
                        else None,
                        name_long=str(row["nameLong"]) if row.get("nameLong") else None,
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise ProviderProtocolError("Malformed instrument row") from exc
        return result

    def _parse_historical(self, payload: Any, request: DataRequest) -> list[MarketBar]:
        if not isinstance(payload, list):
            raise ProviderProtocolError("Expected historicalPrices response to be a JSON array")
        bars: list[MarketBar] = []
        for row in payload:
            if not isinstance(row, dict):
                raise ProviderProtocolError("Historical row is not an object")
            try:
                bars.append(
                    MarketBar(
                        timestamp=self._timestamp(row["timestamp"]),
                        instrument=request.instrument,
                        timeframe=request.timeframe,
                        offer_side=request.offer_side,
                        open=self._decimal(row["open"]),
                        high=self._decimal(row["high"]),
                        low=self._decimal(row["low"]),
                        close=self._decimal(row["close"]),
                        volume=self._decimal(row["volume"])
                        if row.get("volume") is not None
                        else None,
                    )
                )
            except KeyError as exc:
                raise ProviderProtocolError(f"Missing historical field: {exc.args[0]}") from exc
        return bars

    def historical_bars(self, request: DataRequest) -> Sequence[MarketBar]:
        if request.timeframe == Timeframe.TICK:
            raise ValueError("historical_bars handles candles, not ticks")
        if request.end - request.start > timedelta(days=self.settings.max_history_window_days):
            raise ValueError("Request exceeds configured maximum historical window")

        interval = self._source_interval(request.timeframe)
        max_span = interval * (self.settings.max_bars_per_request - 1)
        cursor = request.start
        all_bars: dict[datetime, MarketBar] = {}

        while cursor < request.end:
            chunk_end = min(request.end, cursor + max_span)
            payload = self._request(
                self.HISTORICAL_PATH,
                {
                    "instrument": request.instrument,
                    "timeFrame": request.timeframe.value,
                    "count": self.settings.max_bars_per_request,
                    "start": int(cursor.timestamp() * 1000),
                    "end": int(chunk_end.timestamp() * 1000),
                    "offerSide": request.offer_side.value,
                },
            )
            for bar in self._parse_historical(payload, request):
                if request.start <= bar.timestamp < request.end:
                    all_bars[bar.timestamp] = bar
            if chunk_end >= request.end:
                break
            cursor = chunk_end

        return [all_bars[k] for k in sorted(all_bars)]

    def current_quotes(self, instruments: Sequence[int]) -> Sequence[Quote]:
        if not instruments:
            return []
        payload = self._request(self.CURRENT_PATH, {"instruments": ",".join(map(str, instruments))})
        if not isinstance(payload, list):
            raise ProviderProtocolError("Expected currentPrices response to be a JSON array")

        quotes: list[Quote] = []
        for row in payload:
            if not isinstance(row, dict):
                raise ProviderProtocolError("Quote row is not an object")
            try:
                quotes.append(
                    Quote(
                        timestamp=self._timestamp(row["timestamp"]),
                        instrument=int(row["instrument"]),
                        bid=self._decimal(row["bid"]),
                        ask=self._decimal(row["ask"]),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise ProviderProtocolError("Malformed current quote") from exc
        return quotes

    def health_check(self) -> bool:
        try:
            payload = self._request(self.HEALTH_PATH, {})
            return isinstance(payload, list)
        except Exception:
            return False
