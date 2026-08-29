from research.real_data_coverage import default_instrument_data_plans
from research.real_data_sources import DataField, DataResolution, default_real_data_sources
from trader_bot.asset_universe import AssetClass, default_asset_registry


def test_every_registered_instrument_has_a_real_data_plan():
    registry = default_asset_registry()
    plans = {plan.symbol: plan for plan in default_instrument_data_plans()}
    assert set(plans) == set(registry.symbols())
    for plan in plans.values():
        assert plan.asset_class is registry.require(plan.symbol).asset_class
        assert plan.resolutions
        assert plan.required_fields >= {
            DataField.TIMESTAMP,
            DataField.OPEN,
            DataField.HIGH,
            DataField.LOW,
            DataField.CLOSE,
        }


def test_all_asset_classes_have_covered_instruments():
    plans = default_instrument_data_plans()
    covered = {plan.asset_class for plan in plans}
    assert covered == {
        AssetClass.FOREX,
        AssetClass.CRYPTO,
        AssetClass.METAL,
        AssetClass.COMMODITY,
        AssetClass.EQUITY,
        AssetClass.INDEX,
    }


def test_crypto_uses_high_frequency_real_market_fields():
    plan = next(plan for plan in default_instrument_data_plans() if plan.symbol == "BTC/USD")
    assert plan.source_id == "BINANCE_PUBLIC_MARKET_DATA"
    assert plan.source_symbol == "BTCUSDT"
    assert DataResolution.SECOND in plan.resolutions
    assert DataField.VOLUME in plan.required_fields
    assert DataField.TRADE_COUNT in plan.required_fields


def test_oil_and_metals_use_dukascopy_real_market_source():
    plans = {plan.symbol: plan for plan in default_instrument_data_plans()}
    assert plans["BRENT.CMD/USD"].source_id == "DUKASCOPY_HISTORICAL"
    assert plans["BRENT.CMD/USD"].source_symbol == "BRENT.CMD/USD"
    assert plans["LIGHT.CMD/USD"].source_id == "DUKASCOPY_HISTORICAL"
    assert plans["XAU/USD"].source_id == "DUKASCOPY_HISTORICAL"


def test_stooq_symbols_are_provider_native():
    plans = {plan.symbol: plan for plan in default_instrument_data_plans()}
    assert plans["NVDA"].source_symbol == "nvda.us"
    assert plans["MSFT"].source_symbol == "msft.us"
    assert plans["SPX"].source_symbol == "^spx"
    assert plans["NDX"].source_symbol == "^ndq"
    assert plans["DJI"].source_symbol == "^dji"
    assert plans["NIKKEI"].source_symbol == "^nkx"


def test_each_plan_matches_an_approved_source():
    sources = {source.source_id: source for source in default_real_data_sources()}
    for plan in default_instrument_data_plans():
        source = sources[plan.source_id]
        for resolution in plan.resolutions:
            assert source.supports(plan.asset_class, resolution)
        assert plan.required_fields <= source.required_fields
