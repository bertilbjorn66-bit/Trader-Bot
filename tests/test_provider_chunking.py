from datetime import datetime, timezone

import httpx

from trader_bot.config import Settings
from trader_bot.models import DataRequest, OfferSide, Timeframe
from trader_bot.providers.dukascopy import DukascopyProvider


def test_historical_request_is_chunked_at_provider_limit():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        start = int(request.url.params["start"])
        return httpx.Response(200, json=[{
            "timestamp": start,
            "open": "1",
            "high": "1.1",
            "low": "0.9",
            "close": "1",
            "volume": "1",
        }])

    settings = Settings(max_bars_per_request=2, max_history_window_days=7)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DukascopyProvider(settings=settings, client=client)
    request = DataRequest(
        instrument=1,
        timeframe=Timeframe.ONE_MINUTE,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        offer_side=OfferSide.BID,
    )
    bars = provider.historical_bars(request)
    assert len(calls) >= 3
    assert len(bars) >= 1
    client.close()
