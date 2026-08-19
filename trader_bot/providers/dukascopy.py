from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import Settings, get_settings
from ..data_provider import ProviderProtocolError, ProviderRateLimited, ProviderUnavailable
from ..models import DataRequest, MarketBar, OfferSide, Quote, Timeframe


class DukascopyProvider:
    """Dukascopy REST adapter.

    The adapter is deliberately isolated from the rest of the system. Dukascopy's
    documented historical endpoint caps a response at 5000 records, so requests
    are bounded and the caller receives a normalized, validated sequence.
    """

    BASE_URL = "https://freeserv.dukascopy.com/2.0/"
    HISTORICAL_PATH = "api/historicalPrices"
    CURRENT_PATH = "api/currentPrices"

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(timeout=self.settings.request_timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DukascopyProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, path: str, params: dict[str, Any]) -> Any:
        if self.settings.dukascopy_api_key:
            params["key"] = self.settings.dukascopy_api_key
        try:
            response = self._client.get(self.BASE_URL, params={"path": path, **params})
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        if response.status_code == 429:
            raise ProviderRateLimited("Dukascopy rate limit reached")
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
            # Dukascopy timestamps are Unix milliseconds.
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ProviderProtocolError(f"Invalid timestamp: {value!r}") from exc

    def historical_bars(self, request: DataRequest) -> Sequence[MarketBar]:
        if request.timeframe == Timeframe.TICK:
            raise ValueError("historical_bars returns candles; use a future tick adapter for tick data")

        # The official endpoint allows max=5000. We additionally bound the time
        # range to avoid accidental multi-month single requests.
        if request.end - request.start > timedelta(days=self.settings.max_history_window_days):
            raise ValueError("Request exceeds configured maximum historical window")

        payload = self._request(
            self.HISTORICAL_PATH,
            {
                "instrument": request.instrument,
                "timeFrame": request.timeframe.value,
                "count": self.settings.max_bars_per_request,
                "start": int(request.start.timestamp() * 1000),
                "end": int(request.end.timestamp() * 1000),
                "offerSide": request.offer_side.value,
            },
        )
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
                        volume=self._decimal(row["volume"]) if row.get("volume") is not None else None,
                    )
                )
            except KeyError as exc:
                raise ProviderProtocolError(f"Missing historical field: {exc.args[0]}") from exc

        return sorted(bars, key=lambda x: x.timestamp)

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
            # A lightweight request for a documented endpoint. We do not treat an
            # empty result as proof of market availability; only transport/API health.
            self._request(self.CURRENT_PATH, {"instruments": "1"})
            return True
        except Exception:
            return False
