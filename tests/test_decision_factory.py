from __future__ import annotations

import pytest

from trader_bot.decision import Action
from trader_bot.decision_factory import (
    FactoryInstrumentConfig,
    FactoryState,
    FrozenEvidenceDecisionFactory,
    PromotionCertificate,
)
from trader_bot.risk import OutcomeSummary, RiskLimits
from trader_bot.strategy_binding import FrozenRuntimeContract

CONTRACT = FrozenRuntimeContract(
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


def certificate(*, eligible: bool) -> PromotionCertificate:
    return PromotionCertificate(
        candidate_id="candidate-a",
        research_artifact_digest=CONTRACT.research_artifact_digest,
        research_source_commit=CONTRACT.research_source_commit,
        confirmation_pf_gt_1=eligible,
        confirmation_expectancy_positive=eligible,
        confirmation_sample_min_100=eligible,
        stress_0_2_pips_positive=eligible,
        stress_0_5_pips_positive=eligible,
        stress_1_0_pips_positive=eligible,
        positive_pair_count_min_2=eligible,
        eligible=eligible,
        failure_reasons=() if eligible else ("no_promotion_eligible_candidate",),
    )


def config() -> FactoryInstrumentConfig:
    return FactoryInstrumentConfig(
        direction=Action.BUY,
        summary=OutcomeSummary(
            samples=250,
            win_probability=0.6,
            loss_probability=0.4,
            expected_return=0.1,
            average_win=0.3,
            average_loss=-0.2,
            max_adverse=0.5,
            max_favorable=0.6,
        ),
        risk_limits=RiskLimits(
            minimum_samples=200,
            minimum_win_probability=0.55,
            minimum_expected_return=0.0,
            maximum_adverse=1.0,
        ),
    )


def test_blocked_certificate_never_emits_trade() -> None:
    factory = FrozenEvidenceDecisionFactory(
        contract=CONTRACT,
        certificate=certificate(eligible=False),
        instruments={1: config()},
    )
    decision = factory.decide(1)
    assert factory.state is FactoryState.BLOCKED
    assert decision.action is Action.NO_TRADE
    assert decision.evidence_samples == 0


def test_eligible_factory_uses_existing_decision_kernel() -> None:
    factory = FrozenEvidenceDecisionFactory(
        contract=CONTRACT,
        certificate=certificate(eligible=True),
        instruments={1: config()},
    )
    decision = factory.decide(1)
    assert factory.state is FactoryState.ELIGIBLE
    assert decision.action is Action.BUY
    assert decision.evidence_samples == 250


def test_missing_instrument_is_no_trade() -> None:
    factory = FrozenEvidenceDecisionFactory(
        contract=CONTRACT,
        certificate=certificate(eligible=True),
        instruments={},
    )
    assert factory.decide(1).action is Action.NO_TRADE


def test_certificate_must_match_research_contract() -> None:
    bad = certificate(eligible=True)
    bad = PromotionCertificate(
        **{**bad.__dict__, "research_source_commit": "0" * 40},
    )
    with pytest.raises(ValueError, match="research source commit"):
        FrozenEvidenceDecisionFactory(
            contract=CONTRACT,
            certificate=bad,
            instruments={1: config()},
        )


def test_factory_is_deterministically_fingerprinted() -> None:
    first = FrozenEvidenceDecisionFactory(
        contract=CONTRACT,
        certificate=certificate(eligible=False),
        instruments={1: config()},
    )
    second = FrozenEvidenceDecisionFactory(
        contract=CONTRACT,
        certificate=certificate(eligible=False),
        instruments={1: config()},
    )
    assert first.fingerprint_value == second.fingerprint_value
    assert len(first.fingerprint_value) == 64
