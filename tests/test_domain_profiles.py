from __future__ import annotations

from research.domain_profiles import ContextFeature, domain_profile
from trader_bot.asset_universe import AssetClass, default_asset_registry


def test_crypto_requires_market_microstructure_features() -> None:
    profile = default_asset_registry().require("BTC/USD")
    domain = domain_profile(profile)
    assert ContextFeature.VOLUME in domain.required
    assert ContextFeature.FUNDING in domain.required
    assert ContextFeature.VENUE_MICROSTRUCTURE in domain.required
    assert ContextFeature.CALENDAR not in domain.required


def test_metals_require_session_and_cross_asset_context() -> None:
    profile = default_asset_registry().require("XAU/USD")
    domain = domain_profile(profile)
    assert profile.asset_class is AssetClass.METAL
    assert ContextFeature.SESSION in domain.required
    assert ContextFeature.CROSS_ASSET in domain.required
    assert ContextFeature.EVENT in domain.required


def test_equities_require_calendar_gap_volume_and_event_awareness() -> None:
    profile = default_asset_registry().require("NVDA")
    domain = domain_profile(profile)
    for feature in (
        ContextFeature.CALENDAR,
        ContextFeature.GAP,
        ContextFeature.VOLUME,
        ContextFeature.EVENT,
        ContextFeature.LIQUIDITY,
    ):
        assert feature in domain.required


def test_missing_domain_features_are_explicit() -> None:
    profile = default_asset_registry().require("ETH/USD")
    domain = domain_profile(profile)
    missing = domain.validate_features({ContextFeature.PRICE_STRUCTURE})
    assert "volume" in missing
    assert "funding" in missing
    assert "venue_microstructure" in missing
