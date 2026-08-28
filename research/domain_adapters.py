from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trader_bot.asset_universe import AssetClass, InstrumentProfile
from trader_bot.market_flow import MarketEvidence
from .domain_profiles import ContextFeature, domain_profile


class DomainFeatureSource(Protocol):
    """Supplies only information that existed at the observation timestamp."""

    def features(self, profile: InstrumentProfile) -> set[ContextFeature]: ...

    def evidence(self, profile: InstrumentProfile) -> MarketEvidence: ...


@dataclass(frozen=True, slots=True)
class DomainAdapter:
    """Thin asset-class adapter; intelligence remains provider/research-engine owned."""

    asset_class: AssetClass
    source: DomainFeatureSource

    def observe(self, profile: InstrumentProfile):
        if profile.asset_class is not self.asset_class:
            raise ValueError("adapter asset class does not match instrument")
        available = self.source.features(profile)
        required = domain_profile(profile).required
        return available, required, self.source.evidence(profile)


def required_features_for(asset_class: AssetClass) -> frozenset[ContextFeature]:
    """Expose a stable checklist for an asset-specific research engine."""

    return domain_profile_for(asset_class).required


def domain_profile_for(asset_class: AssetClass):
    from .domain_profiles import DOMAIN_PROFILES

    try:
        return DOMAIN_PROFILES[asset_class]
    except KeyError as exc:
        raise KeyError(f"No domain profile for asset class {asset_class}") from exc
