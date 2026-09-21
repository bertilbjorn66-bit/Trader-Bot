from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trader_bot.asset_universe import AssetClass


class EvidenceDimension(StrEnum):
    STRUCTURE = "STRUCTURE"
    TREND = "TREND"
    MOMENTUM = "MOMENTUM"
    VOLATILITY = "VOLATILITY"
    LIQUIDITY = "LIQUIDITY"
    VOLUME = "VOLUME"
    FUNDING = "FUNDING"
    SESSION = "SESSION"
    CALENDAR = "CALENDAR"
    GAPS = "GAPS"
    EVENTS = "EVENTS"
    CARRY = "CARRY"
    CROSS_MARKET = "CROSS_MARKET"
    VENUE = "VENUE"


@dataclass(frozen=True, slots=True)
class MarketCulture:
    """The native reasoning contract for one asset class.

    Cross-market information is advisory only. A relationship must be explicitly
    allowed and empirically evidenced before it can influence a native decision.
    """

    asset_class: AssetClass
    primary_dimensions: frozenset[EvidenceDimension]
    trade_evolution_dimensions: frozenset[EvidenceDimension]
    invalidation_dimensions: frozenset[EvidenceDimension]
    allowed_external_contexts: frozenset[AssetClass]
    isolation_required: bool = True

    def allows_external_context(self, asset_class: AssetClass) -> bool:
        return asset_class in self.allowed_external_contexts


def default_market_cultures() -> dict[AssetClass, MarketCulture]:
    """Return intentionally distinct native market cultures."""

    common = frozenset(
        {
            EvidenceDimension.STRUCTURE,
            EvidenceDimension.TREND,
            EvidenceDimension.MOMENTUM,
            EvidenceDimension.VOLATILITY,
            EvidenceDimension.LIQUIDITY,
        }
    )

    return {
        AssetClass.FOREX: MarketCulture(
            AssetClass.FOREX,
            primary_dimensions=common
            | frozenset({EvidenceDimension.SESSION, EvidenceDimension.CARRY, EvidenceDimension.EVENTS}),
            trade_evolution_dimensions=common
            | frozenset({EvidenceDimension.SESSION, EvidenceDimension.CARRY}),
            invalidation_dimensions=frozenset({EvidenceDimension.LIQUIDITY, EvidenceDimension.CARRY, EvidenceDimension.EVENTS}),
            allowed_external_contexts=frozenset({AssetClass.FOREX, AssetClass.METAL, AssetClass.INDEX}),
        ),
        AssetClass.CRYPTO: MarketCulture(
            AssetClass.CRYPTO,
            primary_dimensions=common
            | frozenset({EvidenceDimension.VOLUME, EvidenceDimension.FUNDING, EvidenceDimension.VENUE}),
            trade_evolution_dimensions=common
            | frozenset({EvidenceDimension.VOLUME, EvidenceDimension.FUNDING, EvidenceDimension.VENUE}),
            invalidation_dimensions=frozenset({EvidenceDimension.LIQUIDITY, EvidenceDimension.VOLUME, EvidenceDimension.FUNDING, EvidenceDimension.VENUE}),
            allowed_external_contexts=frozenset({AssetClass.CRYPTO, AssetClass.INDEX}),
        ),
        AssetClass.METAL: MarketCulture(
            AssetClass.METAL,
            primary_dimensions=common
            | frozenset({EvidenceDimension.SESSION, EvidenceDimension.CARRY, EvidenceDimension.EVENTS}),
            trade_evolution_dimensions=common
            | frozenset({EvidenceDimension.SESSION, EvidenceDimension.CARRY, EvidenceDimension.EVENTS}),
            invalidation_dimensions=frozenset({EvidenceDimension.LIQUIDITY, EvidenceDimension.EVENTS, EvidenceDimension.CARRY}),
            allowed_external_contexts=frozenset({AssetClass.METAL, AssetClass.FOREX, AssetClass.INDEX}),
        ),
        AssetClass.COMMODITY: MarketCulture(
            AssetClass.COMMODITY,
            primary_dimensions=common
            | frozenset({EvidenceDimension.VOLUME, EvidenceDimension.SESSION, EvidenceDimension.EVENTS, EvidenceDimension.CALENDAR}),
            trade_evolution_dimensions=common
            | frozenset({EvidenceDimension.VOLUME, EvidenceDimension.SESSION, EvidenceDimension.EVENTS, EvidenceDimension.CALENDAR}),
            invalidation_dimensions=frozenset({EvidenceDimension.LIQUIDITY, EvidenceDimension.EVENTS, EvidenceDimension.CALENDAR}),
            allowed_external_contexts=frozenset({AssetClass.COMMODITY, AssetClass.FOREX, AssetClass.METAL, AssetClass.INDEX}),
        ),
        AssetClass.EQUITY: MarketCulture(
            AssetClass.EQUITY,
            primary_dimensions=common
            | frozenset({EvidenceDimension.VOLUME, EvidenceDimension.CALENDAR, EvidenceDimension.GAPS, EvidenceDimension.EVENTS}),
            trade_evolution_dimensions=common
            | frozenset({EvidenceDimension.VOLUME, EvidenceDimension.CALENDAR, EvidenceDimension.GAPS, EvidenceDimension.EVENTS}),
            invalidation_dimensions=frozenset({EvidenceDimension.LIQUIDITY, EvidenceDimension.GAPS, EvidenceDimension.EVENTS, EvidenceDimension.CALENDAR}),
            allowed_external_contexts=frozenset({AssetClass.EQUITY, AssetClass.INDEX}),
        ),
        AssetClass.INDEX: MarketCulture(
            AssetClass.INDEX,
            primary_dimensions=common
            | frozenset({EvidenceDimension.VOLUME, EvidenceDimension.CALENDAR, EvidenceDimension.GAPS, EvidenceDimension.SESSION}),
            trade_evolution_dimensions=common
            | frozenset({EvidenceDimension.VOLUME, EvidenceDimension.CALENDAR, EvidenceDimension.GAPS, EvidenceDimension.SESSION}),
            invalidation_dimensions=frozenset({EvidenceDimension.LIQUIDITY, EvidenceDimension.GAPS, EvidenceDimension.SESSION}),
            allowed_external_contexts=frozenset({AssetClass.INDEX, AssetClass.EQUITY, AssetClass.FOREX}),
        ),
    }
