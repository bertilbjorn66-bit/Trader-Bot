from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trader_bot.asset_universe import AssetClass, InstrumentProfile


class ContextFeature(StrEnum):
    PRICE_STRUCTURE = "price_structure"
    TREND = "trend"
    VOLATILITY = "volatility"
    MOMENTUM = "momentum"
    SPREAD = "spread"
    LIQUIDITY = "liquidity"
    VOLUME = "volume"
    SESSION = "session"
    CALENDAR = "calendar"
    FUNDING = "funding"
    CARRY = "carry"
    GAP = "gap"
    EVENT = "event"
    CROSS_ASSET = "cross_asset"
    VENUE_MICROSTRUCTURE = "venue_microstructure"


@dataclass(frozen=True, slots=True)
class DomainProfile:
    asset_class: AssetClass
    required: frozenset[ContextFeature]
    optional: frozenset[ContextFeature]

    def validate_features(self, available: set[ContextFeature]) -> tuple[str, ...]:
        missing = sorted(feature.value for feature in self.required - available)
        return tuple(missing)


DOMAIN_PROFILES: dict[AssetClass, DomainProfile] = {
    AssetClass.FOREX: DomainProfile(
        AssetClass.FOREX,
        frozenset({
            ContextFeature.PRICE_STRUCTURE,
            ContextFeature.TREND,
            ContextFeature.VOLATILITY,
            ContextFeature.MOMENTUM,
            ContextFeature.SPREAD,
            ContextFeature.SESSION,
            ContextFeature.CARRY,
            ContextFeature.CROSS_ASSET,
        }),
        frozenset({ContextFeature.LIQUIDITY, ContextFeature.EVENT}),
    ),
    AssetClass.CRYPTO: DomainProfile(
        AssetClass.CRYPTO,
        frozenset({
            ContextFeature.PRICE_STRUCTURE,
            ContextFeature.TREND,
            ContextFeature.VOLATILITY,
            ContextFeature.MOMENTUM,
            ContextFeature.SPREAD,
            ContextFeature.LIQUIDITY,
            ContextFeature.VOLUME,
            ContextFeature.FUNDING,
            ContextFeature.VENUE_MICROSTRUCTURE,
        }),
        frozenset({ContextFeature.SESSION, ContextFeature.CROSS_ASSET, ContextFeature.EVENT}),
    ),
    AssetClass.METAL: DomainProfile(
        AssetClass.METAL,
        frozenset({
            ContextFeature.PRICE_STRUCTURE,
            ContextFeature.TREND,
            ContextFeature.VOLATILITY,
            ContextFeature.MOMENTUM,
            ContextFeature.SPREAD,
            ContextFeature.SESSION,
            ContextFeature.CROSS_ASSET,
            ContextFeature.EVENT,
        }),
        frozenset({ContextFeature.LIQUIDITY, ContextFeature.CARRY}),
    ),
    AssetClass.COMMODITY: DomainProfile(
        AssetClass.COMMODITY,
        frozenset({
            ContextFeature.PRICE_STRUCTURE,
            ContextFeature.TREND,
            ContextFeature.VOLATILITY,
            ContextFeature.SPREAD,
            ContextFeature.SESSION,
            ContextFeature.VOLUME,
            ContextFeature.CROSS_ASSET,
            ContextFeature.EVENT,
        }),
        frozenset({ContextFeature.LIQUIDITY, ContextFeature.CARRY}),
    ),
    AssetClass.EQUITY: DomainProfile(
        AssetClass.EQUITY,
        frozenset({
            ContextFeature.PRICE_STRUCTURE,
            ContextFeature.TREND,
            ContextFeature.VOLATILITY,
            ContextFeature.MOMENTUM,
            ContextFeature.SPREAD,
            ContextFeature.LIQUIDITY,
            ContextFeature.VOLUME,
            ContextFeature.CALENDAR,
            ContextFeature.GAP,
            ContextFeature.EVENT,
            ContextFeature.CROSS_ASSET,
        }),
        frozenset({ContextFeature.VENUE_MICROSTRUCTURE}),
    ),
    AssetClass.INDEX: DomainProfile(
        AssetClass.INDEX,
        frozenset({
            ContextFeature.PRICE_STRUCTURE,
            ContextFeature.TREND,
            ContextFeature.VOLATILITY,
            ContextFeature.SPREAD,
            ContextFeature.LIQUIDITY,
            ContextFeature.VOLUME,
            ContextFeature.CALENDAR,
            ContextFeature.GAP,
            ContextFeature.EVENT,
            ContextFeature.CROSS_ASSET,
        }),
        frozenset({ContextFeature.SESSION}),
    ),
}


def domain_profile(profile: InstrumentProfile) -> DomainProfile:
    try:
        return DOMAIN_PROFILES[profile.asset_class]
    except KeyError as exc:
        raise KeyError(f"No domain profile for asset class {profile.asset_class}") from exc
