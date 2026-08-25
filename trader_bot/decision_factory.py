from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .decision import Action, Decision, decide
from .risk import OutcomeSummary, RiskLimits
from .strategy_binding import FrozenRuntimeContract


class FactoryState(StrEnum):
    BLOCKED = "BLOCKED"
    ELIGIBLE = "ELIGIBLE"


@dataclass(frozen=True)
class PromotionCertificate:
    """Immutable proof that a candidate passed every pre-paper promotion gate."""

    candidate_id: str
    research_artifact_digest: str
    research_source_commit: str
    confirmation_pf_gt_1: bool
    confirmation_expectancy_positive: bool
    confirmation_sample_min_100: bool
    stress_0_2_pips_positive: bool
    stress_0_5_pips_positive: bool
    stress_1_0_pips_positive: bool
    positive_pair_count_min_2: bool
    eligible: bool
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty")
        if len(self.research_artifact_digest.removeprefix("sha256:")) != 64:
            raise ValueError("research_artifact_digest must be a SHA-256 digest")
        if len(self.research_source_commit) != 40:
            raise ValueError("research_source_commit must be a 40-character Git SHA")
        expected = all(
            (
                self.confirmation_pf_gt_1,
                self.confirmation_expectancy_positive,
                self.confirmation_sample_min_100,
                self.stress_0_2_pips_positive,
                self.stress_0_5_pips_positive,
                self.stress_1_0_pips_positive,
                self.positive_pair_count_min_2,
            )
        )
        if self.eligible != expected:
            raise ValueError("eligible must equal the conjunction of every promotion gate")
        if self.eligible and self.failure_reasons:
            raise ValueError("eligible certificates cannot contain failure_reasons")

    def fingerprint(self) -> str:
        payload = {
            "candidate_id": self.candidate_id,
            "confirmation_pf_gt_1": self.confirmation_pf_gt_1,
            "confirmation_expectancy_positive": self.confirmation_expectancy_positive,
            "confirmation_sample_min_100": self.confirmation_sample_min_100,
            "stress_0_2_pips_positive": self.stress_0_2_pips_positive,
            "stress_0_5_pips_positive": self.stress_0_5_pips_positive,
            "stress_1_0_pips_positive": self.stress_1_0_pips_positive,
            "positive_pair_count_min_2": self.positive_pair_count_min_2,
            "eligible": self.eligible,
            "failure_reasons": self.failure_reasons,
            "research_artifact_digest": self.research_artifact_digest,
            "research_source_commit": self.research_source_commit,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class FactoryInstrumentConfig:
    direction: Action
    summary: OutcomeSummary
    risk_limits: RiskLimits

    def __post_init__(self) -> None:
        if self.direction not in (Action.BUY, Action.SELL):
            raise ValueError("direction must be BUY or SELL")


class FrozenEvidenceDecisionFactory:
    """Deterministic Quote->Decision binding around the existing decision kernel.

    It never infers a direction from raw price movement and never invents evidence.
    A blocked promotion certificate always produces NO_TRADE.
    """

    def __init__(
        self,
        *,
        contract: FrozenRuntimeContract,
        certificate: PromotionCertificate,
        instruments: Mapping[int, FactoryInstrumentConfig],
    ) -> None:
        if certificate.research_artifact_digest != contract.research_artifact_digest:
            raise ValueError("promotion certificate does not match the frozen research artifact")
        if certificate.research_source_commit != contract.research_source_commit:
            raise ValueError("promotion certificate does not match the frozen research source commit")
        self.contract = contract
        self.certificate = certificate
        self.instruments = MappingProxyType(dict(instruments))
        self._fingerprint = self.fingerprint()

    @property
    def state(self) -> FactoryState:
        return FactoryState.ELIGIBLE if self.certificate.eligible else FactoryState.BLOCKED

    @property
    def fingerprint_value(self) -> str:
        return self._fingerprint

    def decide(self, instrument: int) -> Decision:
        if self.fingerprint() != self._fingerprint:
            raise RuntimeError("frozen decision factory changed after construction")
        if self.state is FactoryState.BLOCKED:
            reason = self.certificate.failure_reasons or ("promotion_certificate_not_eligible",)
            return Decision(Action.NO_TRADE, 0.0, "; ".join(reason), 0)
        config = self.instruments.get(instrument)
        if config is None:
            return Decision(Action.NO_TRADE, 0.0, "No frozen evidence configuration exists for this instrument.", 0)
        return decide(config.summary, config.direction, config.risk_limits)

    def fingerprint(self) -> str:
        payload = {
            "contract": self.contract.fingerprint(),
            "certificate": self.certificate.fingerprint(),
            "instruments": {
                str(key): {
                    "direction": value.direction.value,
                    "summary": {
                        "samples": value.summary.samples,
                        "win_probability": value.summary.win_probability,
                        "loss_probability": value.summary.loss_probability,
                        "expected_return": value.summary.expected_return,
                        "average_win": value.summary.average_win,
                        "average_loss": value.summary.average_loss,
                        "max_adverse": value.summary.max_adverse,
                        "max_favorable": value.summary.max_favorable,
                    },
                    "risk_limits": {
                        "minimum_samples": value.risk_limits.minimum_samples,
                        "minimum_win_probability": value.risk_limits.minimum_win_probability,
                        "minimum_expected_return": value.risk_limits.minimum_expected_return,
                        "maximum_adverse": value.risk_limits.maximum_adverse,
                    },
                }
                for key, value in sorted(self.instruments.items())
            },
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
