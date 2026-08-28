from __future__ import annotations

from trader_bot.asset_universe import AssetClass, default_asset_registry
from research.domain_profiles import ContextFeature, domain_profile
from research.domain_reasoning import (
    Direction,
    DomainContext,
    ExpertFamily,
    ExpertObservation,
    combine_experts,
    required_expert_families,
    validate_context,
)


def _context(symbol: str) -> DomainContext:
    profile = default_asset_registry().require(symbol)
    return DomainContext(
        features={feature: 1.0 for feature in domain_profile(profile).required},
        regime="validated_test_regime",
        quality_score=0.95,
    )


def test_same_expert_vocabulary_exists_for_every_domain() -> None:
    assert len(required_expert_families()) == 8
    assert ExpertFamily.TREND in required_expert_families()
    assert ExpertFamily.ANALOGUE in required_expert_families()


def test_domain_context_is_validated_before_reasoning() -> None:
    registry = default_asset_registry()
    profile = registry.require("BTC/USD")
    context = _context("BTC/USD")
    assert validate_context(profile, context) == ()
    assert ContextFeature.LIQUIDITY in domain_profile(profile).required
    assert ContextFeature.FUNDING in domain_profile(profile).required


def test_experts_combine_with_consensus_without_asset_specific_shortcut() -> None:
    registry = default_asset_registry()
    for symbol in ("EUR/USD", "BTC/USD", "XAU/USD", "NVDA"):
        profile = registry.require(symbol)
        context = _context(symbol)
        observations = tuple(
            ExpertObservation(family, Direction.BUY, 0.80, 0.90)
            for family in required_expert_families()[:5]
        )
        reasoning = combine_experts(profile, context, observations)
        assert reasoning.asset_class is profile.asset_class
        assert reasoning.consensus is Direction.BUY
        assert reasoning.actionable is True


def test_disagreement_degrades_to_no_trade() -> None:
    profile = default_asset_registry().require("XAU/USD")
    context = _context("XAU/USD")
    observations = (
        ExpertObservation(ExpertFamily.TREND, Direction.BUY, 0.90, 1.0),
        ExpertObservation(ExpertFamily.MOMENTUM, Direction.SELL, 0.90, 1.0),
        ExpertObservation(ExpertFamily.BREAKOUT, Direction.BUY, 0.90, 1.0),
        ExpertObservation(ExpertFamily.REVERSAL, Direction.SELL, 0.90, 1.0),
    )
    reasoning = combine_experts(profile, context, observations, maximum_disagreement=0.20)
    assert reasoning.consensus is Direction.NO_TRADE
    assert "expert_disagreement" in reasoning.no_trade_reasons
