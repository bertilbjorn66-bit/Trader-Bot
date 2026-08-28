from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .domain_profiles import ContextFeature


class ExpertFamily(StrEnum):
    TREND = "trend"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    PULLBACK = "pullback"
    VOLATILITY = "volatility"
    REVERSAL = "reversal"
    ANALOGUE = "analogue"


@dataclass(frozen=True, slots=True)
class DomainIntelligenceProfile:
    asset_class: str
    expert_features: Mapping[ExpertFamily, frozenset[ContextFeature]]
    priority_features: frozenset[ContextFeature]

    def required_features_for(self, expert: ExpertFamily) -> frozenset[ContextFeature]:
        return self.expert_features[expert]


_CORE = frozenset({
    ContextFeature.PRICE_STRUCTURE,
    ContextFeature.TREND,
    ContextFeature.VOLATILITY,
    ContextFeature.MOMENTUM,
})

DOMAIN_INTELLIGENCE: dict[str, DomainIntelligenceProfile] = {
    "FOREX": DomainIntelligenceProfile(
        "FOREX",
        {expert: _CORE for expert in ExpertFamily},
        frozenset({ContextFeature.SESSION, ContextFeature.SPREAD, ContextFeature.CARRY, ContextFeature.CROSS_ASSET}),
    ),
    "CRYPTO": DomainIntelligenceProfile(
        "CRYPTO",
        {expert: _CORE | frozenset({ContextFeature.LIQUIDITY, ContextFeature.VOLUME}) for expert in ExpertFamily},
        frozenset({ContextFeature.LIQUIDITY, ContextFeature.VOLUME, ContextFeature.FUNDING, ContextFeature.VENUE_MICROSTRUCTURE}),
    ),
    "METAL": DomainIntelligenceProfile(
        "METAL",
        {expert: _CORE | frozenset({ContextFeature.SESSION, ContextFeature.CROSS_ASSET}) for expert in ExpertFamily},
        frozenset({ContextFeature.SESSION, ContextFeature.CROSS_ASSET, ContextFeature.EVENT}),
    ),
    "EQUITY": DomainIntelligenceProfile(
        "EQUITY",
        {expert: _CORE | frozenset({ContextFeature.VOLUME, ContextFeature.CALENDAR}) for expert in ExpertFamily},
        frozenset({ContextFeature.CALENDAR, ContextFeature.GAP, ContextFeature.VOLUME, ContextFeature.EVENT}),
    ),
}


def domain_intelligence(asset_class: str) -> DomainIntelligenceProfile:
    key = asset_class.upper()
    if key not in DOMAIN_INTELLIGENCE:
        raise KeyError(f"No domain intelligence profile for {asset_class}")
    return DOMAIN_INTELLIGENCE[key]
