from __future__ import annotations

from .decision_factory import FrozenEvidenceDecisionFactory, PromotionCertificate
from .strategy_binding import FrozenRuntimeContract

CURRENT_CONTRACT = FrozenRuntimeContract(
    snapshot_id="runtime-contract-v1",
    strategy_id="candidate-runtime-v1",
    strategy_version="1",
    research_artifact_name="VERIFIED-EMPIRICAL-RESEARCH-REPORT-FINAL",
    research_artifact_digest="sha256:a0f61aeabc371cf3aa3ae38f55ecbf1f869b8f5399b0c3e789482bb6cb10e89c",
    research_source_commit="94eb3343c097eddd1159e4aac1c5a75f6569afad",
    decision_source_sha="515f71b3551502bf052dba8c8895bf8dff98c366",
    risk_source_sha="4bfeeaa8d2be0bbdbab3fe3beb379e34cc49614",
    evaluation_source_sha="bf5a4776b7b0ab2282b58aba757ab41e0eb76490",
    observation_source_sha="094bef5ac47e959367a81ab7c8c8d36c15afa790",
    context_source_sha="96677fa6d68ffda79acdde97cddd03ecf3d6b777",
)

CURRENT_PROMOTION_CERTIFICATE = PromotionCertificate(
    candidate_id="none-promotion-eligible-2026-08-23",
    research_artifact_digest=CURRENT_CONTRACT.research_artifact_digest,
    research_source_commit=CURRENT_CONTRACT.research_source_commit,
    confirmation_pf_gt_1=False,
    confirmation_expectancy_positive=False,
    confirmation_sample_min_100=False,
    stress_0_2_pips_positive=False,
    stress_0_5_pips_positive=False,
    stress_1_0_pips_positive=False,
    positive_pair_count_min_2=False,
    eligible=False,
    failure_reasons=("no_promotion_eligible_candidate",),
)


def current_factory() -> FrozenEvidenceDecisionFactory:
    """Return the repository's current safe factory state.

    The current research certificate intentionally blocks all trading decisions.
    A future eligible certificate must be bound to a new frozen runtime contract.
    """

    return FrozenEvidenceDecisionFactory(
        contract=CURRENT_CONTRACT,
        certificate=CURRENT_PROMOTION_CERTIFICATE,
        instruments={},
    )
