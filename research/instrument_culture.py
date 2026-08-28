from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trader_bot.asset_universe import AssetClass, InstrumentProfile


class MarketElement(StrEnum):
    STRUCTURE = "STRUCTURE"
    TREND = "TREND"
    MOMENTUM = "MOMENTUM"
    VOLATILITY = "VOLATILITY"
    LIQUIDITY = "LIQUIDITY"
    PARTICIPATION = "PARTICIPATION"
    TIMING = "TIMING"
    DRIVERS = "DRIVERS"
    TRADE_EVOLUTION = "TRADE_EVOLUTION"
    HISTORICAL_MEMORY = "HISTORICAL_MEMORY"
    VENUE = "VENUE"
    CONTRACT = "CONTRACT"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    TERM_STRUCTURE = "TERM_STRUCTURE"
    FUNDING = "FUNDING"
    MACRO = "MACRO"


@dataclass(frozen=True, slots=True)
class InstrumentCulture:
    """Native market grammar for one instrument.

    Every instrument has its own culture. Cross-asset information is not part of
    the native culture and can only enter through approved relationship evidence.
    """

    symbol: str
    asset_class: AssetClass
    required_elements: frozenset[MarketElement]
    primary_drivers: tuple[str, ...]
    trade_evolution_keys: tuple[str, ...]
    isolation_required: bool = True

    def validate_for(self, profile: InstrumentProfile) -> None:
        if self.symbol != profile.symbol or self.asset_class is not profile.asset_class:
            raise ValueError("instrument culture does not match instrument profile")
        if not self.required_elements:
            raise ValueError("instrument culture must define required elements")
        if not self.primary_drivers:
            raise ValueError("instrument culture must define primary drivers")
        if not self.trade_evolution_keys:
            raise ValueError("instrument culture must define trade evolution keys")


def culture_for(profile: InstrumentProfile) -> InstrumentCulture:
    """Build a native culture without borrowing another instrument's learned data."""

    common = frozenset(
        {
            MarketElement.STRUCTURE,
            MarketElement.TREND,
            MarketElement.MOMENTUM,
            MarketElement.VOLATILITY,
            MarketElement.LIQUIDITY,
            MarketElement.PARTICIPATION,
            MarketElement.TIMING,
            MarketElement.DRIVERS,
            MarketElement.TRADE_EVOLUTION,
            MarketElement.HISTORICAL_MEMORY,
        }
    )
    if profile.asset_class is AssetClass.FOREX:
        elements = common | {MarketElement.MACRO, MarketElement.FUNDING}
        drivers = ("currencies", "rates", "macro_events", "session_flows")
        trade_keys = ("session", "spread", "carry", "regime")
    elif profile.asset_class is AssetClass.CRYPTO:
        elements = common | {MarketElement.VENUE, MarketElement.FUNDING}
        drivers = ("spot_volume", "funding", "liquidations", "venue_microstructure", "risk_sentiment")
        trade_keys = ("venue", "volume", "funding", "liquidity", "regime")
    elif profile.asset_class is AssetClass.METAL:
        elements = common | {MarketElement.MACRO, MarketElement.FUNDING}
        drivers = ("usd", "real_rates", "macro_events", "session_flows")
        trade_keys = ("session", "usd_context", "rates", "volatility")
    elif profile.asset_class is AssetClass.COMMODITY:
        elements = common | {MarketElement.CONTRACT, MarketElement.TERM_STRUCTURE, MarketElement.MACRO}
        drivers = ("inventory", "seasonality", "term_structure", "macro_events", "contract_roll")
        trade_keys = ("contract", "roll", "seasonality", "inventory", "liquidity")
    elif profile.asset_class is AssetClass.EQUITY:
        elements = common | {MarketElement.VENUE, MarketElement.CONTRACT, MarketElement.CORPORATE_ACTIONS}
        drivers = ("earnings", "corporate_actions", "sector", "index_flows", "macro_events")
        trade_keys = ("session", "gap", "volume", "event", "sector_context")
    else:
        elements = common | {MarketElement.VENUE, MarketElement.MACRO}
        drivers = ("macro", "rates", "risk_sentiment", "breadth")
        trade_keys = ("session", "breadth", "volatility", "macro_context")

    culture = InstrumentCulture(
        symbol=profile.symbol,
        asset_class=profile.asset_class,
        required_elements=elements,
        primary_drivers=drivers,
        trade_evolution_keys=trade_keys,
    )
    culture.validate_for(profile)
    return culture


def default_instrument_cultures(profiles: tuple[InstrumentProfile, ...]) -> tuple[InstrumentCulture, ...]:
    """Return a distinct native culture for every instrument in the registry."""

    return tuple(culture_for(profile) for profile in profiles)
