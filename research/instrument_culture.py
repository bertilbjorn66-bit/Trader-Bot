from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

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


class KnowledgeScope(StrEnum):
    INSTRUMENT = "INSTRUMENT"
    VENUE = "VENUE"
    ASSET_FAMILY = "ASSET_FAMILY"
    ASSET_CLASS = "ASSET_CLASS"


@dataclass(frozen=True, slots=True)
class InstrumentCulture:
    """Native market grammar for one instrument."""

    symbol: str
    venue: str
    asset_class: AssetClass
    required_elements: frozenset[MarketElement]
    primary_drivers: tuple[str, ...]
    trade_evolution_keys: tuple[str, ...]
    isolation_required: bool = True

    def validate_for(self, profile: InstrumentProfile) -> None:
        if (
            self.symbol != profile.symbol
            or self.venue != profile.venue
            or self.asset_class is not profile.asset_class
        ):
            raise ValueError("instrument culture does not match instrument profile")
        if not self.required_elements:
            raise ValueError("instrument culture must define required elements")
        if not self.primary_drivers:
            raise ValueError("instrument culture must define primary drivers")
        if not self.trade_evolution_keys:
            raise ValueError("instrument culture must define trade evolution keys")


@dataclass(frozen=True, slots=True)
class ScopedKnowledge:
    """Auditable learned fact with explicit scope and validity boundaries."""

    symbol: str
    venue: str
    asset_class: AssetClass
    scope: KnowledgeScope
    observed_from: int
    observed_to: int
    evidence_count: int
    confidence: float
    source_fingerprint: str
    review_after: int

    def validate(self) -> None:
        if not self.symbol.strip() or not self.venue.strip():
            raise ValueError("knowledge scope requires symbol and venue")
        if self.observed_from < 0 or self.observed_to < self.observed_from:
            raise ValueError("knowledge observation window is invalid")
        if self.evidence_count <= 0:
            raise ValueError("knowledge evidence_count must be positive")
        if not isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("knowledge confidence must be finite and in [0, 1]")
        if self.review_after < self.observed_to:
            raise ValueError("review_after must not precede observed_to")
        if not self.source_fingerprint.strip():
            raise ValueError("source_fingerprint must be non-empty")


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
    elements: frozenset[MarketElement]
    drivers: tuple[str, ...]
    trade_keys: tuple[str, ...]
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
        elements = common | {MarketElement.VENUE, MarketElement.CORPORATE_ACTIONS, MarketElement.MACRO}
        drivers = ("earnings", "corporate_actions", "sector", "index_flows", "macro_events")
        trade_keys = ("session", "gap", "volume", "event", "sector_context")
    else:
        elements = common | {MarketElement.VENUE, MarketElement.MACRO}
        drivers = ("macro", "rates", "risk_sentiment", "breadth")
        trade_keys = ("session", "breadth", "volatility", "macro_context")

    culture = InstrumentCulture(
        symbol=profile.symbol,
        venue=profile.venue,
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


def validate_knowledge_for_culture(knowledge: ScopedKnowledge, culture: InstrumentCulture) -> None:
    knowledge.validate()
    if knowledge.symbol != culture.symbol or knowledge.venue != culture.venue:
        raise ValueError("knowledge is outside the instrument culture scope")
    if knowledge.asset_class is not culture.asset_class:
        raise ValueError("knowledge asset class does not match instrument culture")


def may_influence_target(
    source: InstrumentCulture,
    target: InstrumentCulture,
    knowledge: ScopedKnowledge,
) -> bool:
    """Return whether a learned fact may influence a target instrument."""

    validate_knowledge_for_culture(knowledge, source)
    if source.symbol == target.symbol and source.venue == target.venue:
        return True
    if knowledge.scope not in {KnowledgeScope.ASSET_FAMILY, KnowledgeScope.ASSET_CLASS}:
        return False
    if source.asset_class is not target.asset_class:
        return False
    return not target.isolation_required or source.asset_class is target.asset_class
