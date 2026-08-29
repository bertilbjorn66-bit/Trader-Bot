from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from trader_bot.asset_universe import AssetClass


class RelationshipStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    WATCH = "WATCH"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    source_symbol: str
    target_symbol: str
    source_class: AssetClass
    target_class: AssetClass
    sample_count: int
    lag_periods: int
    conditional_stability: float
    regime_consistency: float
    effect_size: float
    out_of_sample_confirmed: bool
    cost_aware: bool
    status: RelationshipStatus

    def validate(self) -> None:
        if not self.source_symbol.strip() or not self.target_symbol.strip():
            raise ValueError("relationship symbols must be non-empty")
        if self.source_symbol == self.target_symbol:
            raise ValueError("relationship must connect distinct instruments")
        if self.sample_count <= 0:
            raise ValueError("relationship sample_count must be positive")
        if self.lag_periods < 0:
            raise ValueError("relationship lag_periods must be non-negative")
        for name, value in (
            ("conditional_stability", self.conditional_stability),
            ("regime_consistency", self.regime_consistency),
        ):
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if not isfinite(self.effect_size):
            raise ValueError("effect_size must be finite")

    @property
    def is_approved(self) -> bool:
        return self.status is RelationshipStatus.APPROVED


def approve_relationship(evidence: RelationshipEvidence, *, minimum_samples: int = 1000, minimum_stability: float = 0.70) -> bool:
    """Approve cross-market influence only after explicit empirical requirements."""

    evidence.validate()
    if minimum_samples <= 0 or not 0.0 <= minimum_stability <= 1.0:
        raise ValueError("approval thresholds are invalid")
    return (
        evidence.status is RelationshipStatus.APPROVED
        and evidence.sample_count >= minimum_samples
        and evidence.conditional_stability >= minimum_stability
        and evidence.regime_consistency >= minimum_stability
        and evidence.out_of_sample_confirmed
        and evidence.cost_aware
    )


def may_transfer_context(
    evidence: RelationshipEvidence,
    source_class: AssetClass,
    target_class: AssetClass,
) -> bool:
    evidence.validate()
    if evidence.source_class is not source_class or evidence.target_class is not target_class:
        return False
    return approve_relationship(evidence)
