from trader_bot.asset_universe import AssetClass, default_asset_registry
from research.instrument_culture import MarketElement, culture_for, default_instrument_cultures


def test_every_instrument_has_native_culture():
    registry = default_asset_registry()
    cultures = default_instrument_cultures(tuple(registry.require(symbol) for symbol in registry.symbols()))
    assert {culture.symbol for culture in cultures} == set(registry.symbols())
    for culture in cultures:
        assert MarketElement.HISTORICAL_MEMORY in culture.required_elements
        assert MarketElement.TRADE_EVOLUTION in culture.required_elements
        assert culture.isolation_required


def test_crypto_culture_is_not_equity_culture():
    registry = default_asset_registry()
    crypto = culture_for(registry.require("BTC/USD"))
    equity = culture_for(registry.require("NVDA"))
    assert MarketElement.FUNDING in crypto.required_elements
    assert MarketElement.CORPORATE_ACTIONS not in crypto.required_elements
    assert MarketElement.CORPORATE_ACTIONS in equity.required_elements
    assert MarketElement.FUNDING not in equity.required_elements


def test_each_culture_has_native_drivers_and_trade_keys():
    registry = default_asset_registry()
    for symbol in registry.symbols():
        culture = culture_for(registry.require(symbol))
        assert culture.primary_drivers
        assert culture.trade_evolution_keys
        assert culture.asset_class in set(AssetClass)
