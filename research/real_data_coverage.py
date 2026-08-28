from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from research.real_data_sources import DataField, DataResolution
from trader_bot.asset_universe import AssetClass, default_asset_registry


class CoverageTier(StrEnum):
    HIGH_FREQUENCY = "HIGH_FREQUENCY"
    INTRADAY = "INTRADAY"
    DAILY = "DAILY"


@dataclass(frozen=True, slots=True)
class InstrumentDataPlan:
    """Public-safe declaration of the real dataset required for one instrument."""

    symbol: str
    asset_class: AssetClass
    source_id: str
    source_symbol: str
    resolutions: frozenset[DataResolution]
    required_fields: frozenset[DataField]
    coverage_tier: CoverageTier


def default_instrument_data_plans() -> tuple[InstrumentDataPlan, ...]:
    """Return the explicit real-data feed plan for the current research universe.

    This contains metadata only. Raw market data remains outside the public
    repository and is populated into the private research store by the refresh job.
    """

    plans: list[InstrumentDataPlan] = []
    registry = default_asset_registry()

    for symbol in registry.by_asset_class(AssetClass.FOREX):
        plans.append(
            InstrumentDataPlan(
                symbol=symbol.symbol,
                asset_class=AssetClass.FOREX,
                source_id="DUKASCOPY_HISTORICAL",
                source_symbol=symbol.symbol.replace("/", ""),
                resolutions=frozenset({DataResolution.TICK, DataResolution.MINUTE, DataResolution.HOUR, DataResolution.DAILY}),
                required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.BID, DataField.ASK}),
                coverage_tier=CoverageTier.HIGH_FREQUENCY,
            )
        )

    crypto_source_symbols = {
        "BTC/USD": "BTCUSDT",
        "ETH/USD": "ETHUSDT",
        "SOL/USD": "SOLUSDT",
        "BNB/USD": "BNBUSDT",
        "XRP/USD": "XRPUSDT",
        "ADA/USD": "ADAUSDT",
        "DOGE/USD": "DOGEUSDT",
        "AVAX/USD": "AVAXUSDT",
        "LINK/USD": "LINKUSDT",
    }
    for symbol, source_symbol in crypto_source_symbols.items():
        plans.append(
            InstrumentDataPlan(
                symbol=symbol,
                asset_class=AssetClass.CRYPTO,
                source_id="BINANCE_PUBLIC_MARKET_DATA",
                source_symbol=source_symbol,
                resolutions=frozenset({DataResolution.SECOND, DataResolution.MINUTE, DataResolution.HOUR, DataResolution.DAILY}),
                required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.VOLUME, DataField.TRADE_COUNT}),
                coverage_tier=CoverageTier.HIGH_FREQUENCY,
            )
        )

    for symbol in ("XAU/USD", "XAG/USD", "XPT/USD", "XPD/USD"):
        plans.append(
            InstrumentDataPlan(
                symbol=symbol,
                asset_class=AssetClass.METAL,
                source_id="DUKASCOPY_HISTORICAL",
                source_symbol=symbol.replace("/", ""),
                resolutions=frozenset({DataResolution.MINUTE, DataResolution.HOUR, DataResolution.DAILY}),
                required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.BID, DataField.ASK}),
                coverage_tier=CoverageTier.INTRADAY,
            )
        )

    commodity_symbols = (
        "BRENT.CMD/USD",
        "LIGHT.CMD/USD",
        "GAS.CMD/USD",
        "COPPER.CMD/USD",
        "DIESEL.CMD/USD",
        "COFFEE.CMD/USX",
        "COCOA.CMD/USD",
        "SUGAR.CMD/USD",
        "COTTON.CMD/USX",
        "OJUICE.CMD/USX",
        "SOYBEAN.CMD/USX",
    )
    for symbol in commodity_symbols:
        plans.append(
            InstrumentDataPlan(
                symbol=symbol,
                asset_class=AssetClass.COMMODITY,
                source_id="DUKASCOPY_HISTORICAL",
                source_symbol=symbol,
                resolutions=frozenset({DataResolution.MINUTE, DataResolution.HOUR, DataResolution.DAILY}),
                required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.BID, DataField.ASK}),
                coverage_tier=CoverageTier.INTRADAY,
            )
        )

    tech_symbols = ("NVDA", "MSFT", "AAPL", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "AMD", "TSLA", "ORCL", "CRM", "ADBE", "INTC", "QCOM")
    for symbol in tech_symbols:
        plans.append(
            InstrumentDataPlan(
                symbol=symbol,
                asset_class=AssetClass.EQUITY,
                source_id="STOOQ_MARKET_HISTORY",
                source_symbol=symbol.lower(),
                resolutions=frozenset({DataResolution.DAILY}),
                required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.VOLUME}),
                coverage_tier=CoverageTier.DAILY,
            )
        )

    for symbol in ("SPX", "NDX", "DJI", "FTSE", "DAX", "NIKKEI"):
        plans.append(
            InstrumentDataPlan(
                symbol=symbol,
                asset_class=AssetClass.INDEX,
                source_id="STOOQ_MARKET_HISTORY",
                source_symbol=symbol.lower(),
                resolutions=frozenset({DataResolution.DAILY}),
                required_fields=frozenset({DataField.TIMESTAMP, DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.CLOSE, DataField.VOLUME}),
                coverage_tier=CoverageTier.DAILY,
            )
        )

    return tuple(plans)
