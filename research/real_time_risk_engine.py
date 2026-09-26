"""Fail-closed, low-latency risk layer for research/shadow integration.

No broker or live-order code is contained here. The engine only returns a decision
and risk action so a separate execution adapter can enforce the result.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskAction(str, Enum):
    HOLD = "HOLD"
    ENTER = "ENTER"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    HALT = "HALT"


@dataclass(frozen=True)
class RiskSnapshot:
    now_ms: int
    quote_ts_ms: int
    spread_pips: float
    spread_z: float
    volatility_z: float
    expected_edge_pips: float
    adverse_move_pips: float
    model_confidence: float
    feed_ok: bool = True
    feature_snapshot_ok: bool = True
    model_fresh: bool = True
    broker_ok: bool = True
    position_exists: bool = False
    position_direction: int = 0


@dataclass(frozen=True)
class RiskPolicy:
    max_quote_age_ms: int = 1_500
    max_spread_pips: float = 3.0
    max_spread_z: float = 2.5
    max_volatility_z: float = 4.0
    min_entry_edge_pips: float = 0.40
    min_entry_confidence: float = 0.62
    emergency_adverse_pips: float = 2.0
    emergency_edge_floor_pips: float = -0.50
    hard_drawdown_pct: float = 0.08
    max_consecutive_losses: int = 5


@dataclass
class RiskState:
    equity_peak: float
    equity: float
    consecutive_losses: int = 0
    halted: bool = False

    @property
    def drawdown_pct(self) -> float:
        if self.equity_peak <= 0:
            return 0.0
        return max(0.0, (self.equity_peak - self.equity) / self.equity_peak)


def evaluate(snapshot: RiskSnapshot, state: RiskState, policy: RiskPolicy | None = None) -> RiskAction:
    """Fail closed: any stale/bad input can only HOLD/EXIT/HALT, never ENTER."""
    if policy is None:
        policy = RiskPolicy()
    age = snapshot.now_ms - snapshot.quote_ts_ms
    if state.halted or state.drawdown_pct >= policy.hard_drawdown_pct:
        return RiskAction.HALT
    if state.consecutive_losses >= policy.max_consecutive_losses:
        return RiskAction.HALT
    if not (snapshot.feed_ok and snapshot.feature_snapshot_ok and snapshot.model_fresh and snapshot.broker_ok):
        return RiskAction.EXIT if snapshot.position_exists else RiskAction.HALT
    if age < 0 or age > policy.max_quote_age_ms:
        return RiskAction.EXIT if snapshot.position_exists else RiskAction.HALT
    if snapshot.spread_pips > policy.max_spread_pips or snapshot.spread_z > policy.max_spread_z:
        return RiskAction.EXIT if snapshot.position_exists else RiskAction.HOLD
    if snapshot.volatility_z > policy.max_volatility_z:
        return RiskAction.EXIT if snapshot.position_exists else RiskAction.HOLD

    # Fast protection takes priority over model confidence.
    if snapshot.position_exists:
        if snapshot.adverse_move_pips >= policy.emergency_adverse_pips:
            return RiskAction.EXIT
        if snapshot.expected_edge_pips <= policy.emergency_edge_floor_pips:
            return RiskAction.EXIT
        return RiskAction.HOLD

    if snapshot.expected_edge_pips < policy.min_entry_edge_pips:
        return RiskAction.HOLD
    if snapshot.model_confidence < policy.min_entry_confidence:
        return RiskAction.HOLD
    return RiskAction.ENTER


def should_exit_immediately(snapshot: RiskSnapshot, state: RiskState, policy: RiskPolicy | None = None) -> bool:
    """Minimal O(1) emergency path for a live/shadow adapter's fast loop."""
    if policy is None:
        policy = RiskPolicy()
    if state.halted or state.drawdown_pct >= policy.hard_drawdown_pct:
        return True
    age = snapshot.now_ms - snapshot.quote_ts_ms
    return bool(
        snapshot.position_exists
        and (
            age < 0
            or age > policy.max_quote_age_ms
            or snapshot.adverse_move_pips >= policy.emergency_adverse_pips
            or snapshot.expected_edge_pips <= policy.emergency_edge_floor_pips
            or snapshot.spread_pips > policy.max_spread_pips * 1.5
            or not snapshot.feed_ok
            or not snapshot.feature_snapshot_ok
            or not snapshot.model_fresh
            or not snapshot.broker_ok
        )
    )
