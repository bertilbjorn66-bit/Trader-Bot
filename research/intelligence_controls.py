from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, pstdev
from typing import Iterable, Sequence


@dataclass(frozen=True)
class ExecutionCostModel:
    spread_pips: float
    slippage_pips: float
    latency_pips: float
    financing_pips: float = 0.0

    def total_cost_pips(self) -> float:
        values = (self.spread_pips, self.slippage_pips, self.latency_pips, self.financing_pips)
        if any(value < 0 for value in values):
            raise ValueError("execution costs must be non-negative")
        return sum(values)

    def net_expectancy(self, gross_expectancy_pips: float) -> float:
        return gross_expectancy_pips - self.total_cost_pips()


@dataclass(frozen=True)
class PairRelation:
    pair_a: str
    pair_b: str
    correlation: float
    observations: int

    @property
    def absolute_correlation(self) -> float:
        return abs(self.correlation)


def pearson_correlation(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("correlation requires equal sequences with at least two observations")
    ma = mean(a)
    mb = mean(b)
    da = [x - ma for x in a]
    db = [x - mb for x in b]
    denom = sqrt(sum(x * x for x in da) * sum(x * x for x in db))
    if denom == 0:
        return 0.0
    return sum(x * y for x, y in zip(da, db)) / denom


@dataclass(frozen=True)
class EventRegime:
    event_id: str
    event_type: str
    event_timestamp: int
    known_timestamp: int
    window_start: int
    window_end: int

    def validate_no_lookahead(self) -> None:
        if self.known_timestamp > self.event_timestamp:
            raise ValueError("event information cannot become known after the event timestamp")
        if self.window_start > self.window_end:
            raise ValueError("event regime window is invalid")
        if self.window_start < self.known_timestamp:
            raise ValueError("event regime cannot use observations before the information was known")

    def contains(self, timestamp: int) -> bool:
        self.validate_no_lookahead()
        return self.window_start <= timestamp <= self.window_end


@dataclass(frozen=True)
class CalibrationReport:
    brier_score: float
    expected_calibration_error: float
    observations: int
    bins: int


def calibration_report(probabilities: Sequence[float], outcomes: Sequence[int], bins: int = 10) -> CalibrationReport:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("probabilities and outcomes must be non-empty and equal length")
    if bins < 2:
        raise ValueError("bins must be at least 2")
    if any(p < 0 or p > 1 for p in probabilities):
        raise ValueError("probabilities must be in [0, 1]")
    if any(y not in (0, 1) for y in outcomes):
        raise ValueError("outcomes must be binary")
    brier = mean((p - y) ** 2 for p, y in zip(probabilities, outcomes))
    ece = 0.0
    n = len(probabilities)
    for index in range(bins):
        lo = index / bins
        hi = (index + 1) / bins
        members = [i for i, p in enumerate(probabilities) if lo <= p < hi or (index == bins - 1 and p == hi)]
        if not members:
            continue
        avg_p = mean(probabilities[i] for i in members)
        avg_y = mean(outcomes[i] for i in members)
        ece += len(members) / n * abs(avg_p - avg_y)
    return CalibrationReport(brier, ece, n, bins)


@dataclass(frozen=True)
class DriftReport:
    mean_shift: float
    volatility_ratio: float
    missing_rate_shift: float
    drift: bool


def drift_report(reference: Sequence[float], current: Sequence[float], reference_missing: float = 0.0, current_missing: float = 0.0, mean_threshold: float = 0.5, volatility_ratio_threshold: float = 1.5, missing_shift_threshold: float = 0.1) -> DriftReport:
    if len(reference) < 2 or len(current) < 2:
        raise ValueError("drift requires at least two observations in each window")
    if not 0 <= reference_missing <= 1 or not 0 <= current_missing <= 1:
        raise ValueError("missing rates must be in [0, 1]")
    reference_mean = mean(reference)
    current_mean = mean(current)
    reference_vol = pstdev(reference)
    current_vol = pstdev(current)
    ratio = current_vol / reference_vol if reference_vol > 0 else (float("inf") if current_vol > 0 else 1.0)
    mean_shift = abs(current_mean - reference_mean)
    missing_shift = abs(current_missing - reference_missing)
    drift = mean_shift >= mean_threshold or ratio >= volatility_ratio_threshold or missing_shift >= missing_shift_threshold
    return DriftReport(mean_shift, ratio, missing_shift, drift)


@dataclass(frozen=True)
class WalkForwardFold:
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int

    def validate(self) -> None:
        if not (self.train_start <= self.train_end < self.validation_start <= self.validation_end):
            raise ValueError("walk-forward fold must be strictly chronological")


def make_walk_forward_folds(total_observations: int, train_size: int, validation_size: int, step: int) -> list[WalkForwardFold]:
    if min(total_observations, train_size, validation_size, step) <= 0:
        raise ValueError("walk-forward sizes must be positive")
    folds: list[WalkForwardFold] = []
    start = 0
    while start + train_size + validation_size <= total_observations:
        fold = WalkForwardFold(start, start + train_size - 1, start + train_size, start + train_size + validation_size - 1)
        fold.validate()
        folds.append(fold)
        start += step
    return folds


@dataclass(frozen=True)
class ExpertVote:
    expert_id: str
    direction: str
    confidence: float


@dataclass(frozen=True)
class ExpertRoute:
    action: str
    direction: str | None
    confidence: float
    reason: str


def route_experts(votes: Iterable[ExpertVote], min_confidence: float = 0.65, max_disagreement: float = 0.25) -> ExpertRoute:
    vote_list = list(votes)
    if not vote_list:
        return ExpertRoute("ABSTAIN", None, 0.0, "no expert votes")
    if not 0 < min_confidence <= 1 or not 0 < max_disagreement < 1:
        raise ValueError("invalid routing thresholds")
    if any(v.direction not in {"BUY", "SELL", "NO_TRADE"} for v in vote_list):
        raise ValueError("invalid expert direction")
    eligible = [v for v in vote_list if v.confidence >= min_confidence and v.direction != "NO_TRADE"]
    if not eligible:
        return ExpertRoute("ABSTAIN", None, 0.0, "no sufficiently confident directional expert")
    buy = sum(v.confidence for v in eligible if v.direction == "BUY")
    sell = sum(v.confidence for v in eligible if v.direction == "SELL")
    total = buy + sell
    disagreement = min(buy, sell) / total if total else 1.0
    if disagreement > max_disagreement:
        return ExpertRoute("ABSTAIN", None, 0.0, "expert disagreement exceeds threshold")
    direction = "BUY" if buy > sell else "SELL"
    confidence = max(buy, sell) / total if total else 0.0
    return ExpertRoute("ROUTE", direction, confidence, "dominant expert consensus")


@dataclass(frozen=True)
class IntelligenceControlState:
    execution_cost_ready: bool
    cross_pair_ready: bool
    event_regime_ready: bool
    calibration_ready: bool
    drift_monitor_ready: bool
    walk_forward_ready: bool
    expert_router_ready: bool

    def ready(self) -> bool:
        return all((self.execution_cost_ready, self.cross_pair_ready, self.event_regime_ready, self.calibration_ready, self.drift_monitor_ready, self.walk_forward_ready, self.expert_router_ready))
