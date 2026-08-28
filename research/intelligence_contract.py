from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence

from trader_bot.asset_universe import AssetClass, InstrumentProfile
from .domain_profiles import ContextFeature, domain_profile
from .market_comparison import ComparableState, ComparisonResult, compare_states


class ExpertFamily(StrEnum):
    TREND = "trend"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"
    PULLBACK = "pullback"
    VOLATILITY = "volatility"
    REVERSAL = "reversal"
    ANALOGUE = "analogue"


@dataclass(frozen=True, slots=True)
class ExpertObservation:
    family: ExpertFamily
    direction: str
    confidence: float
    evidence_strength: float


@dataclass(frozen=True, slots=True)
class IntelligenceSnapshot:
    profile: InstrumentProfile
    context_features: frozenset[ContextFeature]
    experts: tuple[ExpertObservation, ...]
    historical_samples: int
    expected_return: float
    uncertainty: float
    liquidity_score: float


def validate_snapshot(snapshot: IntelligenceSnapshot) -> tuple[str, ...]:
    required = domain_profile(snapshot.profile).required
    missing = required - snapshot.context_features
    reasons: list[str] = []
    if missing:
        reasons.append("missing_domain_context:" + ",".join(sorted(feature.value for feature in missing)))
    if snapshot.historical_samples < 1:
        reasons.append("no_historical_support")
    if not snapshot.experts:
        reasons.append("no_expert_observations")
    if not 0.0 <= snapshot.liquidity_score <= 1.0:
        reasons.append("invalid_liquidity_score")
    if snapshot.uncertainty < 0.0:
        reasons.append("invalid_uncertainty")
    return tuple(reasons)


def compatible_comparison(
    left: IntelligenceSnapshot,
    right: IntelligenceSnapshot,
) -> ComparisonResult:
    """Compare two assets without allowing one asset to inherit another's rules."""
    comparable_left = ComparableState(
        left.profile.symbol,
        left.profile.asset_class.value,
        0,
        "unknown",
        {feature.value: 1.0 if feature in left.context_features else 0.0 for feature in domain_profile(left.profile).required},
        left.expected_return,
        left.uncertainty,
        left.liquidity_score,
    )
    comparable_right = ComparableState(
        right.profile.symbol,
        right.profile.asset_class.value,
        0,
        "unknown",
        {feature.value: 1.0 if feature in right.context_features else 0.0 for feature in domain_profile(right.profile).required},
        right.expected_return,
        right.uncertainty,
        right.liquidity_score,
    )
    return compare_states(comparable_left, comparable_right)


def consensus_quality(experts: Sequence[ExpertObservation]) -> float:
    valid = [expert for expert in experts if expert.direction in {"BUY", "SELL"} and 0.0 <= expert.confidence <= 1.0]
    if not valid:
        return 0.0
    buy = sum(expert.confidence * expert.evidence_strength for expert in valid if expert.direction == "BUY")
    sell = sum(expert.confidence * expert.evidence_strength for expert in valid if expert.direction == "SELL")
    total = buy + sell
    if total <= 0.0:
        return 0.0
    return max(buy, sell) / total


def asset_class_label(profile: InstrumentProfile) -> str:
    return AssetClass(profile.asset_class).value
