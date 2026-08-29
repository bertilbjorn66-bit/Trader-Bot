from datetime import datetime, timezone

import httpx
import pytest

from trader_bot.models import DataRequest, OfferSide, Timeframe
from trader_bot.providers.binance import BinanceProvider


def test_binance_parses_klines_and_quotes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/klines"):
            assert request.url.params["symbol"] == "BTCUSDT"
            return httpx.Response(
                200,
                json=[[1704067200000, "42000", "42500", "41500", "42300", "123.4"]],
            )
        if request.url.path.endswith("/ticker/bookTicker"):
            assert request.url.params["symbol"] == "BTCUSDT"
            return httpx.Response(200, json={"symbol": "BTCUSDT", "bidPrice": "42299", "askPrice": "42301"})
        if request.url.path.endswith("/ping"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.binance.com")
    provider = BinanceProvider({7: "BTCUSDT"}, client=client)
    request = DataRequest(
        instrument=7,
        timeframe=Timeframe.ONE_MINUTE,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        offer_side=OfferSide.BID,
    )
    bars = provider.historical_bars(request)
    quotes = provider.current_quotes([7])
    assert len(bars) == 1
    assert bars[0].close == "42300"
    assert len(quotes) == 1
    assert quotes[0].bid == "42299"
    assert quotes[0].ask == "42301"
    assert provider.health_check() is True
    client.close()


def test_binance_rejects_ask_side_candles() -> None:
    provider = BinanceProvider({7: "BTCUSDT"}, client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))))
    request = DataRequest(
        instrument=7,
        timeframe=Timeframe.ONE_MINUTE,
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        offer_side=OfferSide.ASK,
    )
    with pytest.raises(ValueError, match="bid/ask-side"):
        provider.historical_bars(request)
    provider.close()
