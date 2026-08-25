from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .paper_eval import PaperEvaluationResult, PaperEvaluationSpec


class PaperCampaignState(StrEnum):
    CONFIGURED = "CONFIGURED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class PaperCampaignSpec:
    """Immutable contract separating a real paper period from engineering readiness."""

    campaign_id: str
    strategy_fingerprint: str
    evaluation_spec: PaperEvaluationSpec
    start_at: datetime
    end_at: datetime
    minimum_accepted_observations: int
    minimum_expectancy: Decimal = Decimal("0")
    minimum_profit_factor: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.campaign_id.strip():
            raise ValueError("campaign_id must be non-empty")
        if not self.strategy_fingerprint.strip():
            raise ValueError("strategy_fingerprint must be non-empty")
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("campaign timestamps must be timezone-aware")
        if self.start_at >= self.end_at:
            raise ValueError("campaign start_at must be before end_at")
        if self.minimum_accepted_observations <= 0:
            raise ValueError("minimum_accepted_observations must be positive")
        if self.minimum_profit_factor <= Decimal("1"):
            raise ValueError("minimum_profit_factor must be greater than 1")

    @property
    def evaluation_fingerprint(self) -> str:
        return self.evaluation_spec.fingerprint()

    def fingerprint(self) -> str:
        payload = {
            "campaign_id": self.campaign_id,
            "strategy_fingerprint": self.strategy_fingerprint,
            "evaluation_fingerprint": self.evaluation_fingerprint,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "minimum_accepted_observations": self.minimum_accepted_observations,
            "minimum_expectancy": str(self.minimum_expectancy),
            "minimum_profit_factor": str(self.minimum_profit_factor),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class PaperCampaignResult:
    state: PaperCampaignState
    campaign_fingerprint: str
    strategy_fingerprint: str
    accepted_observations: int
    rejected_observations: int
    evaluation: PaperEvaluationResult | None
    failure_reasons: tuple[str, ...]


class PaperPerformanceGate:
    """Independent final verdict for a completed real-observation paper period."""

    def __init__(self, spec: PaperCampaignSpec) -> None:
        self.spec = spec
        self._fingerprint = spec.fingerprint()

    def evaluate(
        self,
        *,
        accepted_observations: int,
        rejected_observations: int,
        evaluation: PaperEvaluationResult | None,
        finalized_at: datetime,
    ) -> PaperCampaignResult:
        if self.spec.fingerprint() != self._fingerprint:
            raise RuntimeError("paper campaign specification changed after campaign creation")
        if finalized_at.tzinfo is None:
            raise ValueError("finalized_at must be timezone-aware")
        if accepted_observations < 0 or rejected_observations < 0:
            raise ValueError("observation counts cannot be negative")
        if finalized_at < self.spec.start_at:
            raise ValueError("campaign cannot finalize before its start")

        failures: list[str] = []
        if finalized_at < self.spec.end_at:
            failures.append("campaign_window_not_complete")
        if accepted_observations < self.spec.minimum_accepted_observations:
            failures.append("minimum_accepted_observations_not_met")
        if evaluation is None:
            failures.append("paper_evaluation_missing")
        else:
            if evaluation.spec_fingerprint != self.spec.evaluation_fingerprint:
                failures.append("evaluation_specification_mismatch")
            if evaluation.closed_trades < self.spec.evaluation_spec.minimum_closed_trades:
                failures.append("minimum_closed_trades_not_met")
            if not evaluation.passed:
                failures.extend(evaluation.failure_reasons)
            if evaluation.expectancy <= self.spec.minimum_expectancy:
                failures.append("paper_expectancy_not_positive")
            if evaluation.profit_factor is None or evaluation.profit_factor <= self.spec.minimum_profit_factor:
                failures.append("paper_profit_factor_not_above_threshold")

        if failures:
            state = (
                PaperCampaignState.INCOMPLETE
                if any(reason.endswith("not_met") or reason.endswith("not_complete") or reason.endswith("missing") for reason in failures)
                and not any(reason in {"paper_expectancy_not_positive", "paper_profit_factor_not_above_threshold", "maximum_session_loss_breached"} for reason in failures)
                else PaperCampaignState.FAILED
            )
        else:
            state = PaperCampaignState.COMPLETE

        return PaperCampaignResult(
            state=state,
            campaign_fingerprint=self._fingerprint,
            strategy_fingerprint=self.spec.strategy_fingerprint,
            accepted_observations=accepted_observations,
            rejected_observations=rejected_observations,
            evaluation=evaluation,
            failure_reasons=tuple(dict.fromkeys(failures)),
        )
