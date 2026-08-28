from research.domain_profiles import ContextFeature, domain_profile
from research.multi_asset_engine import (
    FixedEvidenceAdapter,
    MultiAssetResearchEngine,
    ResearchVerdict,
)
from trader_bot.asset_universe import AssetClass, ResearchStatus, default_asset_registry
from trader_bot.market_flow import MarketEvidence
from trader_bot.portfolio_flow import PortfolioSnapshot


def _engine() -> MultiAssetResearchEngine:
    evidence = MarketEvidence(
        expected_return=0.20,
        confidence=0.85,
        samples=1000,
        maximum_adverse=0.20,
        edge_after_costs=0.10,
        data_healthy=True,
        context_known=True,
        agreement=0.90,
    )
    adapters = {
        asset_class: FixedEvidenceAdapter(asset_class, evidence)
        for asset_class in (
            AssetClass.FOREX,
            AssetClass.CRYPTO,
            AssetClass.METAL,
            AssetClass.COMMODITY,
            AssetClass.EQUITY,
            AssetClass.INDEX,
        )
    }
    return MultiAssetResearchEngine(adapters)


def test_each_asset_class_has_its_own_context_contract() -> None:
    registry = default_asset_registry()
    for symbol in ("EUR/USD", "BTC/USD", "XAU/USD", "NVDA"):
        profile = registry.require(symbol)
        required = domain_profile(profile).required
        assert ContextFeature.PRICE_STRUCTURE in required
        assert ContextFeature.VOLATILITY in required


def test_research_only_assets_are_not_operationally_ready() -> None:
    registry = default_asset_registry()
    assert registry.require("BTC/USD").research_status is ResearchStatus.RESEARCH_ONLY
    assert registry.require("XAU/USD").research_status is ResearchStatus.RESEARCH_ONLY
    assert registry.require("NVDA").research_status is ResearchStatus.RESEARCH_ONLY


def test_research_planned_status_is_not_ready() -> None:
    registry = default_asset_registry()
    assert registry.require("BTC/USD").is_research_ready is False


def test_missing_asset_adapter_blocks_without_pressure() -> None:
    registry = default_asset_registry()
    engine = MultiAssetResearchEngine({})
    decision = engine.evaluate(registry.require("BTC/USD"))
    assert decision.verdict is ResearchVerdict.BLOCKED
    assert decision.allocation is None
    assert decision.flow.risk_budget_fraction == 0.0


def test_validated_domain_can_reach_portfolio_allocation() -> None:
    registry = default_asset_registry()
    engine = _engine()
    decision = engine.evaluate(registry.require("EUR/USD"), PortfolioSnapshot())
    assert decision.verdict is ResearchVerdict.READY
    assert decision.allocation is not None
    assert decision.allocation.allowed is True


def test_new_asset_requires_its_own_validated_research_before_ready() -> None:
    registry = default_asset_registry()
    engine = _engine()
    decision = engine.evaluate(registry.require("BTC/USD"), PortfolioSnapshot())
    assert decision.verdict is ResearchVerdict.WAIT
    assert decision.allocation is None
    assert "instrument_not_research_ready" in decision.reasons
