from __future__ import annotations

from trader_bot.asset_universe import AssetClass, ResearchStatus, default_asset_registry
from trader_bot.market_flow import FlowPolicy, FlowState, MarketEvidence, assess_flow
from trader_bot.portfolio_flow import PortfolioLimits, PortfolioSnapshot, PositionRisk, allocate
from research.asset_research_contract import ResearchMode, contract_for


def test_default_universe_separates_asset_classes_and_research_status() -> None:
    registry = default_asset_registry()
    assert registry.require("EUR/USD").asset_class is AssetClass.FOREX
    assert registry.require("BTC/USD").asset_class is AssetClass.CRYPTO
    assert registry.require("XAU/USD").asset_class is AssetClass.METAL
    assert registry.require("NVDA").asset_class is AssetClass.EQUITY
    assert registry.require("BTC/USD").research_status is ResearchStatus.RESEARCH_ONLY
    assert registry.require("EUR/USD").research_status is ResearchStatus.EXISTING_VALIDATED_DOMAIN


def test_unknown_or_unhealthy_market_does_not_create_trade_pressure() -> None:
    registry = default_asset_registry()
    assessment = assess_flow(
        registry.require("BTC/USD"),
        MarketEvidence(
            expected_return=0.01,
            confidence=0.9,
            samples=500,
            maximum_adverse=0.2,
            edge_after_costs=0.01,
            data_healthy=False,
            context_known=False,
        ),
    )
    assert assessment.state is FlowState.BLOCKED
    assert assessment.risk_budget_fraction == 0.0
    assert "market_data_unhealthy" in assessment.reasons
    assert "market_context_unknown" in assessment.reasons


def test_ready_flow_is_bounded_before_portfolio_allocation() -> None:
    registry = default_asset_registry()
    profile = registry.require("EUR/USD")
    assessment = assess_flow(
        profile,
        MarketEvidence(
            expected_return=0.15,
            confidence=0.80,
            samples=1000,
            maximum_adverse=0.30,
            edge_after_costs=0.10,
            data_healthy=True,
            context_known=True,
            agreement=0.90,
        ),
    )
    assert assessment.state is FlowState.READY
    allocation = allocate("EUR/USD", AssetClass.FOREX, assessment, PortfolioSnapshot())
    assert allocation.allowed is True
    assert 0.0 < allocation.risk_fraction <= PortfolioLimits().max_single_position_fraction


def test_portfolio_limits_prevent_correlated_risk_accumulation_by_class() -> None:
    registry = default_asset_registry()
    profile = registry.require("BTC/USD")
    assessment = assess_flow(
        profile,
        MarketEvidence(
            expected_return=1.0,
            confidence=0.9,
            samples=1000,
            maximum_adverse=0.1,
            edge_after_costs=0.5,
            data_healthy=True,
            context_known=True,
            agreement=0.9,
        ),
    )
    snapshot = PortfolioSnapshot(
        open_positions=(
            PositionRisk("ETH/USD", AssetClass.CRYPTO, 0.01),
        )
    )
    allocation = allocate("BTC/USD", AssetClass.CRYPTO, assessment, snapshot)
    assert allocation.allowed is False
    assert allocation.reason == "asset_class_risk_limit_reached"


def test_equity_contract_demands_calendar_and_volume_awareness() -> None:
    profile = default_asset_registry().require("NVDA")
    contract = contract_for(profile)
    assert contract.mode is ResearchMode.HISTORICAL
    assert contract.require_calendar_awareness is True
    assert contract.require_volume_features is True
    contract.validate_profile(profile)
