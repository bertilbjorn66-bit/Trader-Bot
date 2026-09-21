from datetime import datetime, timezone

import pytest

from research.scoped_knowledge import KnowledgeScope, RelationshipEvidence, ScopedKnowledge
from trader_bot.asset_universe import AssetClass


def scope(symbol: str, venue: str | None = None) -> KnowledgeScope:
    return KnowledgeScope(AssetClass.CRYPTO, symbol, venue)


def knowledge() -> ScopedKnowledge:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ScopedKnowledge(
        scope=scope("BTC/USD", "Binance Spot"),
        claim="example",
        evidence_count=100,
        confidence=0.8,
        observed_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
        observed_to=datetime(2025, 12, 1, tzinfo=timezone.utc),
        learned_at=now,
        review_after=datetime(2027, 1, 1, tzinfo=timezone.utc),
        source_fingerprint="sha256:example",
    )


def test_knowledge_is_instrument_and_venue_scoped():
    item = knowledge()
    assert item.applies_to(AssetClass.CRYPTO, "BTC/USD", "Binance Spot")
    assert not item.applies_to(AssetClass.CRYPTO, "ETH/USD", "Binance Spot")
    assert not item.applies_to(AssetClass.CRYPTO, "BTC/USD", "Other Venue")
    assert not item.applies_to(AssetClass.FOREX, "BTC/USD", "Binance Spot")


def test_knowledge_rejects_naive_timestamps():
    item = knowledge()
    broken = ScopedKnowledge(
        scope=item.scope,
        claim=item.claim,
        evidence_count=item.evidence_count,
        confidence=item.confidence,
        observed_from=datetime(2024, 1, 1),
        observed_to=item.observed_to,
        learned_at=item.learned_at,
        review_after=item.review_after,
        source_fingerprint=item.source_fingerprint,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        broken.validate()


def test_relationship_requires_explicit_approval():
    evidence = RelationshipEvidence(
        source_scope=scope("BTC/USD", "Binance Spot"),
        target_scope=scope("ETH/USD", "Binance Spot"),
        relationship_id="btc-eth-regime-1",
        lag_periods=1,
        regime_conditioned=True,
        sample_size=500,
        stability_score=0.85,
        approved=False,
    )
    assert not evidence.can_influence(evidence.source_scope, evidence.target_scope)
    evidence = RelationshipEvidence(
        source_scope=evidence.source_scope,
        target_scope=evidence.target_scope,
        relationship_id=evidence.relationship_id,
        lag_periods=evidence.lag_periods,
        regime_conditioned=evidence.regime_conditioned,
        sample_size=evidence.sample_size,
        stability_score=evidence.stability_score,
        approved=True,
    )
    assert evidence.can_influence(evidence.source_scope, evidence.target_scope)
