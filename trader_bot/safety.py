from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .decision import Action, Decision


@dataclass(frozen=True)
class SafetyState:
    live_trading_enabled: bool = False
    emergency_stop: bool = True
    stale_data: bool = True
    spread_ok: bool = False
    daily_loss_limit_hit: bool = False


def authorize_live_action(decision: Decision, state: SafetyState) -> Action:
    # Default-deny. A trading decision is not an execution authorization.
    if decision.action not in (Action.BUY, Action.SELL):
        return Action.NO_TRADE
    if not state.live_trading_enabled:
        return Action.NO_TRADE
    if state.emergency_stop or state.stale_data or not state.spread_ok or state.daily_loss_limit_hit:
        return Action.NO_TRADE
    return decision.action


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
