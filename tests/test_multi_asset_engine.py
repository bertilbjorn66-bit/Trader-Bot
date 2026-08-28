from trader_bot.asset_universe import ResearchStatus, default_asset_registry


def test_planned_instruments_are_not_research_ready():
    registry = default_asset_registry()
    profile = registry.require("BTC/USD")
    assert profile.research_status is ResearchStatus.RESEARCH_ONLY
    assert profile.is_research_ready is False


def test_symbol_normalization_is_explicit():
    registry = default_asset_registry()
    assert registry.get("eur/usd") is not None
    assert registry.get("eur/usd").symbol == "EUR/USD"
