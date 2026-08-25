from __future__ import annotations

import pytest

from trader_bot.strategy_binding import (
    FrozenRuntimeContract,
    StrategyBindingGate,
    StrategyBindingState,
)


BASE = dict(
    snapshot_id="runtime-contract-v1",
    strategy_id="candidate-runtime-v1",
    strategy_version="1",
    research_artifact_name="VERIFIED-EMPIRICAL-RESEARCH-REPORT-FINAL",
    research_artifact_digest="sha256:a0f61aeabc371cf3aa3ae38f55ecbf1f869b8f5399b0c3e789482bb6cb10e89c",
    research_source_commit="94eb3343c097eddd1159e4aac1c5a75f6569afad",
    decision_source_sha="515f71b3551502bf052dba8c8895bf8dff98c366",
    risk_source_sha="4bfeeaa8a2dbe0bbdbab3fe3beb379e34cc49614",
    evaluation_source_sha="bf5a4776b7b0ab2282b58aba757ab41e0eb76490",
    observation_source_sha="094bef5ac47e959367a81ab7c8c8d36c15afa790",
    context_source_sha="96677fa6d68ffda79acdde97cddd03ecf3d6b777",
)


def test_unbound_factory_is_blocked() -> None:
    result = StrategyBindingGate(FrozenRuntimeContract(**BASE)).evaluate()
    assert result.state is StrategyBindingState.BLOCKED
    assert result.failure_reasons == ("decision_factory_not_bound",)
    assert len(result.snapshot_fingerprint) == 64


def test_bound_factory_verifies() -> None:
    contract = FrozenRuntimeContract(
        **BASE,
        decision_factory_id="candidate-a-quote-decision-v1",
        decision_factory_source_sha="1234567890abcdef1234567890abcdef12345678",
    )
    result = StrategyBindingGate(contract).evaluate()
    assert result.state is StrategyBindingState.VERIFIED
    assert result.failure_reasons == ()


def test_contract_mutation_after_gate_creation_is_detected() -> None:
    contract = FrozenRuntimeContract(**BASE)
    gate = StrategyBindingGate(contract)
    object.__setattr__(contract, "strategy_version", "2")
    with pytest.raises(RuntimeError, match="frozen runtime contract changed"):
        gate.evaluate()


def test_invalid_research_digest_is_rejected() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        FrozenRuntimeContract(**{**BASE, "research_artifact_digest": "sha256:bad"})


def test_invalid_source_sha_is_rejected() -> None:
    with pytest.raises(ValueError, match="40-character Git SHA"):
        FrozenRuntimeContract(**{**BASE, "decision_source_sha": "bad"})
