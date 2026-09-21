import pytest

from research.relationship_evidence import (
    RelationshipEvidence,
    RelationshipStatus,
    approve_relationship,
    may_transfer_context,
)
from trader_bot.asset_universe import AssetClass


def evidence(**overrides) -> RelationshipEvidence:
    values = {
        "source_symbol": "BTC/USD",
        "target_symbol": "ETH/USD",
        "source_class": AssetClass.CRYPTO,
        "target_class": AssetClass.CRYPTO,
        "sample_count": 2500,
        "lag_periods": 1,
        "conditional_stability": 0.82,
        "regime_consistency": 0.79,
        "effect_size": 0.25,
        "out_of_sample_confirmed": True,
        "cost_aware": True,
        "status": RelationshipStatus.APPROVED,
    }
    values.update(overrides)
    return RelationshipEvidence(**values)


def test_approved_relationship_can_transfer_context():
    item = evidence()
    assert approve_relationship(item)
    assert may_transfer_context(item, AssetClass.CRYPTO, AssetClass.CRYPTO)


def test_in_sample_only_relationship_is_rejected():
    assert not approve_relationship(evidence(out_of_sample_confirmed=False))


def test_unstable_relationship_is_rejected():
    assert not approve_relationship(evidence(conditional_stability=0.69))


def test_insufficient_sample_is_rejected():
    assert not approve_relationship(evidence(sample_count=999))


def test_not_cost_aware_is_rejected():
    assert not approve_relationship(evidence(cost_aware=False))


def test_wrong_domain_context_is_rejected():
    item = evidence()
    assert not may_transfer_context(item, AssetClass.CRYPTO, AssetClass.METAL)


def test_invalid_relationship_self_link_is_rejected():
    with pytest.raises(ValueError, match="distinct instruments"):
        evidence(target_symbol="BTC/USD").validate()
