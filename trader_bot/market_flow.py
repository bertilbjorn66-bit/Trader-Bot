from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from .asset_universe import InstrumentProfile


class FlowState(StrEnum):
    BLOCKED = "BLOCKED"
    WAIT = "WAIT"
    READY = "READY"


@dataclass(frozen=True, slots=True)
class MarketEvidence:
    """Normalized evidence supplied by an asset-specific research engine."""

    expected_return: float | None
    confidence: float | None
    samples: int
    maximum_adverse: float | None
    edge_after_costs: float | None
    data_healthy: bool
    context_known: bool
    agreement: float | None = None

    def __post_init__(self) -> None:
        if self.samples < 0:
            raise ValueError("samples cannot be negative")
        for name, value in (
            ("expected_return", self.expected_return),
            ("confidence", self.confidence),
            ("maximum_adverse", self.maximum_adverse),
            ("edge_after_costs", self.edge_after_costs),
            ("agreement", self.agreement),
        ):
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite when provided")
        for name, value in (("confidence", self.confidence), ("agreement", self.agreement)):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.maximum_adverse is not None and self.maximum_adverse < 0:
            raise ValueError("maximum_adverse cannot be negative")


@dataclass(frozen=True, slots=True)
class FlowPolicy:
    minimum_samples: int = 200
    minimum_confidence: float = 0.55
    minimum_edge_after_costs: float = 0.0
    maximum_adverse: float = 1.0
    minimum_agreement: float = 0.70

    def __post_init__(self) -> None:
        if self.minimum_samples < 0:
            raise ValueError("minimum_samples cannot be negative")
        for name, value in (
            ("minimum_confidence", self.minimum_confidence),
            ("minimum_agreement", self.minimum_agreement),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.maximum_adverse < 0:
            raise ValueError("maximum_adverse cannot be negative")


@dataclass(frozen=True, slots=True)
class FlowAssessment:
    state: FlowState
    reasons: tuple[str, ...]
    risk_budget_fraction: float


def assess_flow(
    profile: InstrumentProfile,
    evidence: MarketEvidence,
    policy: FlowPolicy | None = None,
) -> FlowAssessment:
    """Move only when the whole chain is ready; otherwise wait without forcing action."""

    active_policy = policy if policy is not None else FlowPolicy()
    reasons: list[str] = []
    if not evidence.data_healthy:
        reasons.append("market_data_unhealthy")
    if not evidence.context_known:
        reasons.append("market_context_unknown")
    if evidence.samples < active_policy.minimum_samples:
        reasons.append("evidence_floor_not_met")
    if evidence.confidence is None or evidence.confidence < active_policy.minimum_confidence:
        reasons.append("confidence_below_floor")
    if evidence.edge_after_costs is None or evidence.edge_after_costs <= active_policy.minimum_edge_after_costs:
        reasons.append("edge_after_costs_not_positive")
    if evidence.maximum_adverse is None or evidence.maximum_adverse > active_policy.maximum_adverse:
        reasons.append("adverse_risk_above_limit")
    if evidence.agreement is not None and evidence.agreement < active_policy.minimum_agreement:
        reasons.append("expert_agreement_below_floor")
    if not profile.is_research_ready:
        reasons.append("instrument_not_research_ready")

    if not evidence.data_healthy or not evidence.context_known:
        return FlowAssessment(FlowState.BLOCKED, tuple(reasons), 0.0)
    if reasons:
        return FlowAssessment(FlowState.WAIT, tuple(reasons), 0.0)
    return FlowAssessment(FlowState.READY, (), 1.0)
