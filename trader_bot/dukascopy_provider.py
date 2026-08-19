from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings
from .data_provider import (
    MarketDataProvider,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from .models import DataRequest, Instrument, MarketBar, OfferSide, Quote, Timeframe


_TIMEFRAME_STEP = {
    Timeframe.TEN_SECONDS: timedelta(seconds=10),
    Timeframe.ONE_MINUTE: timedelta(minutes=1),
    Timeframe.TEN_MINUTES: timedelta(minutes=10),
    Timeframe.ONE_HOUR: timedelta(hours=1),
    Timeframe.ONE_DAY: timedelta(days=1),
    Timeframe.ONE_DAY_EET: timedelta(days=1),
}


class DukascopyProvider(MarketDataProvider):
    """Provider for Dukascopy's public historical/quote API."""

    BASE_URL = "https://freeserv.dukascopy.com/2.0/"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.Client(timeout=settings.request_timeout_seconds)
        self._owns_client = client is None
        self._instrument_cache: tuple[Instrument, ...] | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> DukascopyProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        reraise=True,
    )
    def _get(self, params: dict[str, object]) -> Any:
        merged = dict(params)
        if self.settings.dukascopy_api_key:
            merged["key"] = self.settings.dukascopy_api_key
        try:
            response = self._client.get(self.BASE_URL, params={"path": params["path"], **merged})
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderUnavailable("Dukascopy request failed") from exc
        if response.status_code == 429:
            raise ProviderRateLimited("Dukascopy rate limit reached")
        if response.status_code >= 500:
            raise ProviderUnavailable(f"Dukascopy server error: {response.status_code}")
        if response.status_code >= 400:
            raise ProviderProtocolError(f"Dukascopy request rejected: {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderProtocolError("Dukascopy returned invalid JSON") from exc

    def instruments(self) -> tuple[Instrument, ...]:
        if self._instrument_cache is not None:
            return self._instrument_cache
        payload = self._get({"path": "api/instrumentList"})
        if not isinstance(payload, list):
            raise ProviderProtocolError("instrumentList response is not an array")
        result: list[Instrument] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            try:
                result.append(
                    Instrument(
                        id=int(row["id"]),
                        name=str(row["name"]),
                        pip_value=Decimal(str(row["pipValue"])) if row.get("pipValue") is not None else None,
                        name_long=str(row["nameLong"]) if row.get("nameLong") is not None else None,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if not result:
            raise ProviderProtocolError("Dukascopy returned no usable instruments")
        self._instrument_cache = tuple(sorted(result, key=lambda item: item.id))
        return self._instrument_cache

    def historical_bars(self, request: DataRequest) -> tuple[MarketBar, ...]:
        if request.timeframe is Timeframe.TICK:
            raise ProviderProtocolError("Tick retrieval is not part of the candle provider")
        step = _TIMEFRAME_STEP.get(request.timeframe)
        if step is None:
            raise ProviderProtocolError("Unsupported provider timeframe")
        windows: list[tuple[datetime, datetime]] = []
        cursor = request.start
        span = step * (self.settings.max_bars_per_request - 1)
        max_span = timedelta(days=self.settings.max_history_window_days)
        span = min(span, max_span)
        while cursor < request.end:
            window_end = min(request.end, cursor + span + step)
            windows.append((cursor, window_end))
            cursor = window_end

        by_timestamp: dict[datetime, MarketBar] = {}
        for start, end in windows:
            payload = self._get(
                {
                    "path": "api/historicalPrices",
                    "instrument": request.instrument,
                    "timeFrame": request.timeframe.value,
                    "count": self.settings.max_bars_per_request,
                    "start": int(start.timestamp() * 1000),
                    "end": int(end.timestamp() * 1000),
                    "dayStartTime": "UTC",
                    "offerSide": request.offer_side.value,
                }
            )
            candles = payload.get("candles") if isinstance(payload, dict) else None
            if not isinstance(candles, list):
                raise ProviderProtocolError("historicalPrices response has no candles array")
            for row in candles:
                bar = self._parse_candle(row, request)
                if request.start <= bar.timestamp < request.end:
                    by_timestamp[bar.timestamp] = bar

        return tuple(sorted(by_timestamp.values(), key=lambda bar: bar.timestamp))

    def current_quotes(self, instruments: tuple[int, ...] | list[int]) -> tuple[Quote, ...]:
        payload = self._get({"path": "api/currentPrices", "instruments": ",".join(str(i) for i in instruments)})
        rows = payload.get("quotes") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ProviderProtocolError("currentPrices response is not an array")
        result: list[Quote] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                timestamp = _parse_timestamp(row.get("timestamp"))
                result.append(
                    Quote(
                        timestamp=timestamp,
                        instrument=int(row["instrument"]),
                        bid=Decimal(str(row["bid"])),
                        ask=Decimal(str(row["ask"])),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(result)

    def health_check(self) -> bool:
        try:
            self.instruments()
            return True
        except (ProviderUnavailable, ProviderProtocolError, ProviderRateLimited):
            return False

    @staticmethod
    def _parse_candle(row: object, request: DataRequest) -> MarketBar:
        if not isinstance(row, dict):
            raise ProviderProtocolError("Malformed candle row")
        timestamp = _parse_timestamp(row.get("timestamp"))
        prefix = "bid_" if request.offer_side is OfferSide.BID else "ask_"
        try:
            open_price = Decimal(str(row[f"{prefix}open"]))
            high_price = Decimal(str(row[f"{prefix}high"]))
            low_price = Decimal(str(row[f"{prefix}low"]))
            close_price = Decimal(str(row[f"{prefix}close"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderProtocolError("Dukascopy candle row is missing expected OHLC fields") from exc
        volume = row.get("volume")
        return MarketBar(
            timestamp=timestamp,
            instrument=request.instrument,
            timeframe=request.timeframe,
            offer_side=request.offer_side,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=Decimal(str(volume)) if volume is not None else None,
        )


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    raise ProviderProtocolError("Invalid Dukascopy timestamp")
