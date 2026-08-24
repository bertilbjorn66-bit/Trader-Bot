import httpx

from trader_bot.models import Instrument
from trader_bot.providers.dukascopy import DukascopyProvider


def test_instrument_catalog_is_discovered_from_provider():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["path"] == "api/instrumentList"
        return httpx.Response(200, json=[{"id": 42, "name": "EURUSD", "pipValue": "0.0001", "nameLong": "EUR/USD"}])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DukascopyProvider(client=client)
    instruments = provider.instruments()
    assert instruments == [Instrument(id=42, name="EURUSD", pip_value="0.0001", name_long="EUR/USD")]
    client.close()
