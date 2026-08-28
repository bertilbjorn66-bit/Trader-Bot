import pytest

from trader_bot.asset_universe import AssetClass, default_asset_registry
from research.instrument_culture import (
    KnowledgeScope,
    MarketElement,
    ScopedKnowledge,
    culture_for,
    default_instrument_cultures,
    may_influence_target,
)


def _knowledge(symbol: str, venue: str, scope: KnowledgeScope = KnowledgeScope.INSTRUMENT) -> ScopedKnowledge:
    registry = default_asset_registry()
    return ScopedKnowledge(
        symbol=symbol,
        venue=venue,
        asset_class=registry.require(symbol).asset_class,
        scope=scope,
        observed_from=1,
        observed_to=100,
        evidence_count=1000,
        confidence=0.8,
        source_fingerprint="sha256:test",
        review_after=200,
    )


def test_every_instrument_has_native_culture():
    registry = default_asset_registry()
    cultures = default_instrument_cultures(tuple(registry.require(symbol) for symbol in registry.symbols()))
    assert {culture.symbol for culture in cultures} == set(registry.symbols())
    for culture in cultures:
        assert MarketElement.HISTORICAL_MEMORY in culture.required_elements
        assert MarketElement.TRADE_EVOLUTION in culture.required_elements
        assert culture.isolation_required


def test_crypto_culture_is_not_equity_culture():
    registry = default_asset_registry()
    crypto = culture_for(registry.require("BTC/USD"))
    equity = culture_for(registry.require("NVDA"))
    assert MarketElement.FUNDING in crypto.required_elements
    assert MarketElement.CORPORATE_ACTIONS not in crypto.required_elements
    assert MarketElement.CORPORATE_ACTIONS in equity.required_elements
    assert MarketElement.FUNDING not in equity.required_elements


def test_each_culture_has_native_drivers_and_trade_keys():
    registry = default_asset_registry()
    for symbol in registry.symbols():
        culture = culture_for(registry.require(symbol))
        assert culture.primary_drivers
        assert culture.trade_evolution_keys
        assert culture.asset_class in set(AssetClass)


def test_same_instrument_knowledge_can_influence_itself():
    registry = default_asset_registry()
    source = culture_for(registry.require("BTC/USD"))
    target = culture_for(registry.require("BTC/USD"))
    assert may_influence_target(source, target, _knowledge("BTC/USD", source.venue))


def test_instrument_scoped_knowledge_cannot_cross_symbols():
    registry = default_asset_registry()
    source = culture_for(registry.require("BTC/USD"))
    target = culture_for(registry.require("ETH/USD"))
    assert not may_influence_target(source, target, _knowledge("BTC/USD", source.venue))


def test_knowledge_must_match_source_venue():
    registry = default_asset_registry()
    source = culture_for(registry.require("BTC/USD"))
    with pytest.raises(ValueError, match="outside the instrument culture scope"):
        may_influence_target(source, source, _knowledge("BTC/USD", "OTHER_VENUE"))


def test_broad_same_class_knowledge_can_be_shared():
    registry = default_asset_registry()
    source = culture_for(registry.require("BTC/USD"))
    target = culture_for(registry.require("ETH/USD"))
    assert may_influence_target(
        source,
        target,
        _knowledge("BTC/USD", source.venue, KnowledgeScope.ASSET_CLASS),
    )


def test_cross_asset_knowledge_is_never_implicitly_shared():
    registry = default_asset_registry()
    source = culture_for(registry.require("BTC/USD"))
    target = culture_for(registry.require("XAU/USD"))
    assert not may_influence_target(
        source,
        target,
        _knowledge("BTC/USD", source.venue, KnowledgeScope.ASSET_CLASS),
    )


def test_invalid_knowledge_confidence_is_rejected():
    with pytest.raises(ValueError, match="confidence"):
        ScopedKnowledge(
            symbol="BTC/USD",
            venue="MULTI_VENUE_PENDING",
            asset_class=AssetClass.CRYPTO,
            scope=KnowledgeScope.INSTRUMENT,
            observed_from=1,
            observed_to=100,
            evidence_count=1000,
            confidence=1.1,
            source_fingerprint="sha256:test",
            review_after=200,
        ).validate()
