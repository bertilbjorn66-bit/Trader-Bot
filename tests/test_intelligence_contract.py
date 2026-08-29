from research.domain_profiles import ContextFeature, domain_profile
from research.intelligence_contract import (
    ExpertFamily,
    ExpertObservation,
    IntelligenceSnapshot,
    consensus_quality,
    validate_snapshot,
)
from trader_bot.asset_universe import default_asset_registry


def snapshot(symbol: str) -> IntelligenceSnapshot:
    profile = default_asset_registry().require(symbol)
    return IntelligenceSnapshot(
        profile=profile,
        context_features=frozenset(domain_profile(profile).required),
        experts=tuple(
            ExpertObservation(family, "BUY", 0.75, 0.8)
            for family in ExpertFamily
        ),
        historical_samples=500,
        expected_return=0.25,
        uncertainty=0.10,
        liquidity_score=0.90,
    )


def test_all_expert_families_exist_as_shared_reasoning_contract() -> None:
    assert set(ExpertFamily) == {
        ExpertFamily.TREND,
        ExpertFamily.MOMENTUM,
        ExpertFamily.BREAKOUT,
        ExpertFamily.MEAN_REVERSION,
        ExpertFamily.PULLBACK,
        ExpertFamily.VOLATILITY,
        ExpertFamily.REVERSAL,
        ExpertFamily.ANALOGUE,
    }


def test_domain_requirements_remain_asset_specific() -> None:
    registry = default_asset_registry()
    fx = domain_profile(registry.require("EUR/USD"))
    crypto = domain_profile(registry.require("BTC/USD"))
    equity = domain_profile(registry.require("NVDA"))
    assert ContextFeature.CARRY in fx.required
    assert ContextFeature.FUNDING in crypto.required
    assert ContextFeature.CALENDAR in equity.required
    assert ContextFeature.VOLUME in crypto.required
    assert ContextFeature.VOLUME in equity.required


def test_valid_snapshot_passes_contract() -> None:
    result = validate_snapshot(snapshot("BTC/USD"))
    assert result == ()


def test_missing_domain_context_is_rejected() -> None:
    base = snapshot("BTC/USD")
    reduced = IntelligenceSnapshot(
        base.profile,
        frozenset({ContextFeature.PRICE_STRUCTURE}),
        base.experts,
        base.historical_samples,
        base.expected_return,
        base.uncertainty,
        base.liquidity_score,
    )
    assert any(reason.startswith("missing_domain_context:") for reason in validate_snapshot(reduced))


def test_consensus_quality_rewards_agreement_without_forcing_direction() -> None:
    experts = (
        ExpertObservation(ExpertFamily.TREND, "BUY", 0.8, 0.9),
        ExpertObservation(ExpertFamily.MOMENTUM, "BUY", 0.7, 0.8),
        ExpertObservation(ExpertFamily.REVERSAL, "SELL", 0.4, 0.5),
    )
    quality = consensus_quality(experts)
    assert 0.5 < quality <= 1.0
