from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from statistics import mean
from typing import Iterable

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
    instrument: str
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
        if not self.instrument.strip():
            raise ValueError("instrument must be non-empty")
        if self.instrument != self.instrument.upper():
            raise ValueError("instrument must be normalized uppercase")
        for name, value in (
            ("unrealized_return", self.unrealized_return),
            ("max_favorable_excursion", self.max_favorable_excursion),
            ("max_adverse_excursion", self.max_adverse_excursion),
            ("thesis_strength", self.thesis_strength),
            ("liquidity_score", self.liquidity_score),
            ("cost_score", self.cost_score),
            ("context_score", self.context_score),
            ("invalidation_score", self.invalidation_score),
        ):
            if not isinstance(value, (int, float)) or value != value or value in {float("inf"), float("-inf")}:
                raise ValueError(f"{name} must be finite")
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


@dataclass(frozen=True, slots=True)
class TradeTrajectorySummary:
    instrument: str
    asset_class: AssetClass
    trajectories: int
    positive_final_return_rate: float
    mean_final_return: float
    mean_max_favorable_excursion: float
    mean_max_adverse_excursion: float
    deterioration_rate: float


def summarize_trade_trajectories(
    trajectories: Iterable[Iterable[TradeObservation]],
    *,
    policy: TradeEvolutionPolicy | None = None,
) -> tuple[TradeTrajectorySummary, ...]:
    """Learn completed trade paths without crossing instrument or chronological boundaries."""

    active_policy = policy if policy is not None else TradeEvolutionPolicy()
    active_policy.validate()
    groups: dict[tuple[str, AssetClass], list[list[TradeObservation]]] = {}
    for raw_trajectory in trajectories:
        trajectory = list(raw_trajectory)
        if not trajectory:
            continue
        for observation in trajectory:
            observation.validate()
        keys = {(observation.instrument, observation.asset_class) for observation in trajectory}
        if len(keys) != 1:
            raise ValueError("a trade trajectory cannot mix instruments or asset classes")
        timestamps = [observation.timestamp for observation in trajectory]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            raise ValueError("trade observations must have unique strictly increasing timestamps")
        groups.setdefault(next(iter(keys)), []).append(trajectory)

    summaries: list[TradeTrajectorySummary] = []
    for (instrument, asset_class), asset_trajectories in sorted(groups.items()):
        final_returns = [path[-1].unrealized_return for path in asset_trajectories]
        favorable_excursions = [max(point.max_favorable_excursion for point in path) for path in asset_trajectories]
        adverse_excursions = [max(point.max_adverse_excursion for point in path) for path in asset_trajectories]
        deterioration = [
            any(
                point.invalidation_score >= active_policy.deterioration_threshold
                for point in path[1:]
            )
            for path in asset_trajectories
        ]
        summaries.append(
            TradeTrajectorySummary(
                instrument=instrument,
                asset_class=asset_class,
                trajectories=len(asset_trajectories),
                positive_final_return_rate=sum(value > 0.0 for value in final_returns) / len(final_returns),
                mean_final_return=mean(final_returns),
                mean_max_favorable_excursion=mean(favorable_excursions),
                mean_max_adverse_excursion=mean(adverse_excursions),
                deterioration_rate=sum(deterioration) / len(deterioration),
            )
        )
    return tuple(summaries)


def _domain_penalty(observation: TradeObservation) -> float:
    """Return a conservative score penalty for domain conditions affecting an open thesis."""

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
    """Evaluate an open trade without reordering or changing its entry thesis."""

    active_policy = policy if policy is not None else TradeEvolutionPolicy()
    active_policy.validate()
    if not observations:
        raise ValueError("at least one trade observation is required")
    for observation in observations:
        observation.validate()
    identities = {(observation.instrument, observation.asset_class) for observation in observations}
    if len(identities) != 1:
        raise ValueError("a trade cannot change instrument or asset class during its lifecycle")
    timestamps = [observation.timestamp for observation in observations]
    if timestamps != sorted(timestamps):
        raise ValueError("trade observations must be supplied chronologically")
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("trade observations must have unique timestamps")

    current = observations[-1]
    periods = len(observations)

    if current.invalidation_score >= active_policy.invalidation_threshold:
        return TradeEvolutionState(
            TradePhase.EXIT_READY,
            TradeAction.EXIT,
            0.0,
            ("trade_thesis_invalidated",),
        )

    # Thesis/context deterioration is the lifecycle risk signal. Liquidity and
    # cost penalties lower confidence but do not independently manufacture an
    # exit on a newly opened trade; hard invalidation remains explicit above.
    thesis_context_stability = min(current.thesis_strength, current.context_score)
    deterioration = max(0.0, 1.0 - thesis_context_stability)

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
            max(0.0, thesis_context_stability),
            tuple(reasons),
        )

    score = min(1.0, thesis_context_stability - _domain_penalty(current))
    if current.unrealized_return > 0 and current.thesis_strength >= active_policy.favorable_lock_threshold:
        if periods <= active_policy.early_periods:
            phase = TradePhase.EARLY
        elif periods >= active_policy.mature_periods:
            phase = TradePhase.MATURE
        else:
            phase = TradePhase.DEVELOPING
        return TradeEvolutionState(phase, TradeAction.HOLD, max(0.0, score), ("thesis_remains_supported",))

    phase = TradePhase.EARLY if periods <= active_policy.early_periods else TradePhase.DEVELOPING
    return TradeEvolutionState(phase, TradeAction.HOLD, max(0.0, score), ("trade_remains_valid",))
