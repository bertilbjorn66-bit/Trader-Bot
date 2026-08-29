from datetime import datetime, timezone

import httpx
import pytest

from trader_bot.models import DataRequest, OfferSide, Timeframe
from trader_bot.providers.stooq import StooqProvider


def test_stooq_parses_daily_csv() -> None:
    payload = "Date,Open,High,Low,Close,Volume\n2024-01-02,100,105,99,104,1200000\n2024-01-03,104,106,103,105,1300000\n"

    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=payload)),
    )
    provider = StooqProvider({9: "nvda.us"}, client=client)
    request = DataRequest(
        instrument=9,
        timeframe=Timeframe.ONE_DAY,
        start=datetime(2024, 1, 2, tzinfo=timezone.utc),
        end=datetime(2024, 1, 4, tzinfo=timezone.utc),
        offer_side=OfferSide.BID,
    )
    bars = provider.historical_bars(request)
    assert len(bars) == 2
    assert bars[0].close == "104"
    assert bars[1].volume == "1300000"
    client.close()


def test_stooq_rejects_intraday_requests() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="")))
    provider = StooqProvider({9: "nvda.us"}, client=client)
    request = DataRequest(
        instrument=9,
        timeframe=Timeframe.ONE_HOUR,
        start=datetime(2024, 1, 2, tzinfo=timezone.utc),
        end=datetime(2024, 1, 3, tzinfo=timezone.utc),
        offer_side=OfferSide.BID,
    )
    with pytest.raises(ValueError, match="only supports daily"):
        provider.historical_bars(request)
    provider.close()
