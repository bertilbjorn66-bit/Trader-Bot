from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Mapping

from trader_bot.asset_universe import AssetClass, InstrumentProfile

from .domain_profiles import ContextFeature, domain_profile


class ExpertFamily(StrEnum):
    TREND = "trend"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    PULLBACK = "pullback"
    VOLATILITY = "volatility"
    REVERSAL = "reversal"
    ANALOGUE = "analogue"


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True, slots=True)
class ExpertObservation:
    family: ExpertFamily
    direction: Direction
    confidence: float
    evidence_strength: float
    rationale: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (("confidence", self.confidence), ("evidence_strength", self.evidence_strength)):
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between 0 and 1")


@dataclass(frozen=True, slots=True)
class DomainContext:
    features: Mapping[ContextFeature, float | str | bool | None]
    regime: str
    quality_score: float

    def __post_init__(self) -> None:
        if not self.regime.strip():
            raise ValueError("regime must be non-empty")
        if not isfinite(self.quality_score) or not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class DomainReasoning:
    asset_class: AssetClass
    observations: tuple[ExpertObservation, ...]
    context_quality: float
    consensus: Direction
    consensus_confidence: float
    disagreement: float
    no_trade_reasons: tuple[str, ...]

    @property
    def actionable(self) -> bool:
        return self.consensus is not Direction.NO_TRADE and not self.no_trade_reasons


def validate_context(profile: InstrumentProfile, context: DomainContext) -> tuple[str, ...]:
    required = domain_profile(profile).required
    available = set(context.features)
    missing = tuple(sorted(feature.value for feature in required - available))
    reasons = [f"missing_context:{feature}" for feature in missing]
    if context.quality_score <= 0.0:
        reasons.append("context_quality_zero")
    return tuple(reasons)


def combine_experts(profile: InstrumentProfile, context: DomainContext, observations: tuple[ExpertObservation, ...], *, minimum_confidence: float = 0.65, maximum_disagreement: float = 0.25) -> DomainReasoning:
    if not 0.0 < minimum_confidence <= 1.0:
        raise ValueError("minimum_confidence must be in (0, 1]")
    if not 0.0 <= maximum_disagreement < 1.0:
        raise ValueError("maximum_disagreement must be in [0, 1)")
    reasons = list(validate_context(profile, context))
    eligible = [item for item in observations if item.direction is not Direction.NO_TRADE and item.confidence >= minimum_confidence]
    if not eligible:
        reasons.append("no_sufficiently_confident_experts")
        return DomainReasoning(profile.asset_class, observations, context.quality_score, Direction.NO_TRADE, 0.0, 1.0, tuple(reasons))
    weighted = {
        Direction.BUY: sum(item.confidence * item.evidence_strength for item in eligible if item.direction is Direction.BUY),
        Direction.SELL: sum(item.confidence * item.evidence_strength for item in eligible if item.direction is Direction.SELL),
    }
    total = weighted[Direction.BUY] + weighted[Direction.SELL]
    disagreement = min(weighted.values()) / total if total else 1.0
    consensus = Direction.BUY if weighted[Direction.BUY] > weighted[Direction.SELL] else Direction.SELL
    confidence = max(weighted.values()) / total if total else 0.0
    if disagreement > maximum_disagreement:
        reasons.append("expert_disagreement")
        consensus = Direction.NO_TRADE
        confidence = 0.0
    if context.quality_score < 0.70:
        reasons.append("context_quality_below_operating_floor")
        consensus = Direction.NO_TRADE
        confidence = 0.0
    return DomainReasoning(profile.asset_class, observations, context.quality_score, consensus, min(0.99, confidence), disagreement, tuple(reasons))


def required_expert_families() -> tuple[ExpertFamily, ...]:
    return tuple(ExpertFamily)
