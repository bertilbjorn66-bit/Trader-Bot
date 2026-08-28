from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trader_bot.asset_universe import AssetClass


class TradePhase(StrEnum):
    ENTRY = "ENTRY"
    EARLY = "EARLY"
    DEVELOPING = "DEVELOPING"
    MATURE = "MATURE"
    DETERIORATING = "DETERIORATING"
    EXIT_READY = "EXIT_READY"
    CLOSED = "CLOSED"


class TradeAction(StrEnum):
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    FREEZE = "FREEZE"


@dataclass(frozen=True, slots=True)
class TradeObservation:
    timestamp: int
    asset_class: AssetClass
    unrealized_return: float
    max_favorable_excursion: float
    max_adverse_excursion: float
    thesis_strength: float
    liquidity_score: float
    cost_score: float
    context_score: float
    invalidation_score: float

    def validate(self) -> None:
        if self.timestamp < 0:
            raise ValueError("timestamp must be non-negative")
        for name, value in (
            ("thesis_strength", self.thesis_strength),
            ("liquidity_score", self.liquidity_score),
            ("cost_score", self.cost_score),
            ("context_score", self.context_score),
            ("invalidation_score", self.invalidation_score),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.max_favorable_excursion < 0.0:
            raise ValueError("max_favorable_excursion cannot be negative")
        if self.max_adverse_excursion < 0.0:
            raise ValueError("max_adverse_excursion cannot be negative")


@dataclass(frozen=True, slots=True)
class TradeEvolutionPolicy:
    early_periods: int = 3
    mature_periods: int = 12
    deterioration_threshold: float = 0.45
    invalidation_threshold: float = 0.80
    minimum_liquidity: float = 0.35
    minimum_cost_score: float = 0.35
    favorable_lock_threshold: float = 0.70

    def validate(self) -> None:
        if self.early_periods <= 0 or self.mature_periods <= self.early_periods:
            raise ValueError("trade evolution periods must be positive and ordered")
        for name, value in (
            ("deterioration_threshold", self.deterioration_threshold),
            ("invalidation_threshold", self.invalidation_threshold),
            ("minimum_liquidity", self.minimum_liquidity),
            ("minimum_cost_score", self.minimum_cost_score),
            ("favorable_lock_threshold", self.favorable_lock_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.deterioration_threshold >= self.invalidation_threshold:
            raise ValueError("deterioration threshold must be below invalidation threshold")


@dataclass(frozen=True, slots=True)
class TradeEvolutionState:
    phase: TradePhase
    action: TradeAction
    score: float
    reasons: tuple[str, ...]


def _domain_penalty(observation: TradeObservation) -> float:
    """Return a conservative penalty for domain conditions that threaten an open thesis."""

    penalty = 0.0
    if observation.asset_class is AssetClass.CRYPTO:
        if observation.liquidity_score < 0.50:
            penalty += 0.20
        if observation.cost_score < 0.50:
            penalty += 0.15
    elif observation.asset_class is AssetClass.EQUITY:
        if observation.context_score < 0.50:
            penalty += 0.15
    elif observation.asset_class is AssetClass.METAL:
        if observation.context_score < 0.50:
            penalty += 0.10
    elif observation.asset_class in {AssetClass.COMMODITY, AssetClass.INDEX}:
        if observation.liquidity_score < 0.45:
            penalty += 0.10
    else:
        if observation.cost_score < 0.40:
            penalty += 0.10
    return min(1.0, penalty)


def evaluate_trade_evolution(
    observations: list[TradeObservation],
    *,
    policy: TradeEvolutionPolicy | None = None,
) -> TradeEvolutionState:
    """Evaluate an open trade using its evolution history without changing its entry thesis."""

    active_policy = policy or TradeEvolutionPolicy()
    active_policy.validate()
    if not observations:
        raise ValueError("at least one trade observation is required")
    for observation in observations:
        observation.validate()
    ordered = sorted(observations, key=lambda item: item.timestamp)
    current = ordered[-1]
    periods = len(ordered)

    if current.invalidation_score >= active_policy.invalidation_threshold:
        return TradeEvolutionState(
            TradePhase.EXIT_READY,
            TradeAction.EXIT,
            0.0,
            ("trade_thesis_invalidated",),
        )

    domain_penalty = _domain_penalty(current)
    stability = min(current.thesis_strength, current.context_score, current.liquidity_score, current.cost_score)
    deterioration = max(0.0, 1.0 - stability + domain_penalty)

    if deterioration >= active_policy.invalidation_threshold:
        return TradeEvolutionState(
            TradePhase.EXIT_READY,
            TradeAction.EXIT,
            max(0.0, 1.0 - deterioration),
            ("trade_conditions_no_longer_viable",),
        )

    if deterioration >= active_policy.deterioration_threshold:
        action = TradeAction.REDUCE if current.unrealized_return > 0 else TradeAction.FREEZE
        reasons = ["trade_thesis_deteriorating"]
        if current.liquidity_score < active_policy.minimum_liquidity:
            reasons.append("liquidity_deterioration")
        if current.cost_score < active_policy.minimum_cost_score:
            reasons.append("cost_conditions_deteriorating")
        return TradeEvolutionState(
            TradePhase.DETERIORATING,
            action,
            max(0.0, 1.0 - deterioration),
            tuple(reasons),
        )

    if current.unrealized_return > 0 and current.thesis_strength >= active_policy.favorable_lock_threshold:
        phase = TradePhase.MATURE if periods >= active_policy.mature_periods else TradePhase.DEVELOPING
        return TradeEvolutionState(phase, TradeAction.HOLD, min(1.0, stability), ("thesis_remains_supported",))

    phase = TradePhase.EARLY if periods <= active_policy.early_periods else TradePhase.DEVELOPING
    return TradeEvolutionState(phase, TradeAction.HOLD, min(1.0, stability), ("trade_remains_valid",))
