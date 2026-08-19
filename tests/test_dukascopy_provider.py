from datetime import datetime, timezone

import httpx

from trader_bot.models import DataRequest, OfferSide, Timeframe
from trader_bot.providers.dukascopy import DukascopyProvider


def test_provider_normalizes_documented_historical_response():
    payload = [{
        "timestamp": 1767225600000,
        "open": "1.1000",
        "high": "1.1010",
        "low": "1.0990",
        "close": "1.1005",
        "volume": "12",
    }]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["path"] == "api/historicalPrices"
        assert request.url.params["offerSide"] == "B"
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DukascopyProvider(client=client)
    request = DataRequest(
        instrument=1,
        timeframe=Timeframe.ONE_MINUTE,
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        offer_side=OfferSide.BID,
    )
    bars = provider.historical_bars(request)
    assert len(bars) == 1
    assert bars[0].offer_side == OfferSide.BID
    assert str(bars[0].close) == "1.1005"
    client.close()
