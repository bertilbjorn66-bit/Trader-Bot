from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .decision_factory import FactoryState
from .execution import ExecutionGateway, ExecutionStatus


class PromotionState(StrEnum):
    BLOCKED = "BLOCKED"
    PAPER_READY = "PAPER_READY"
    SHADOW_READY = "SHADOW_READY"
    LIVE_READY = "LIVE_READY"


@dataclass(frozen=True)
class PromotionInputs:
    empirical_confirmation_passed: bool
    robustness_passed: bool
    factory_state: FactoryState
    paper_passed: bool
    shadow_passed: bool
    credentials_configured: bool
    emergency_stop_tested: bool
    daily_loss_tested: bool
    stale_spread_tested: bool
    broker_limits_verified: bool
    human_approval_present: bool
    live_execution_enabled: bool = False


@dataclass(frozen=True)
class PromotionResult:
    state: PromotionState
    reasons: tuple[str, ...]


class FinalPromotionGate:
    """Monotonic, default-deny promotion state machine for Gates 6-8."""

    def evaluate(self, inputs: PromotionInputs) -> PromotionResult:
        reasons: list[str] = []
        if not inputs.empirical_confirmation_passed:
            reasons.append("empirical_confirmation_not_passed")
        if not inputs.robustness_passed:
            reasons.append("robustness_not_passed")
        if inputs.factory_state is not FactoryState.ELIGIBLE:
            reasons.append("strategy_factory_not_eligible")

        if reasons:
            return PromotionResult(PromotionState.BLOCKED, tuple(reasons))

        if not inputs.paper_passed:
            return PromotionResult(PromotionState.PAPER_READY, ("paper_period_not_passed",))

        if not inputs.shadow_passed:
            return PromotionResult(PromotionState.SHADOW_READY, ("shadow_period_not_passed",))

        for name, ok in (
            ("credentials_not_configured", inputs.credentials_configured),
            ("emergency_stop_not_tested", inputs.emergency_stop_tested),
            ("daily_loss_not_tested", inputs.daily_loss_tested),
            ("stale_spread_not_tested", inputs.stale_spread_tested),
            ("broker_limits_not_verified", inputs.broker_limits_verified),
            ("human_approval_missing", inputs.human_approval_present),
        ):
            if not ok:
                reasons.append(name)
        if not inputs.live_execution_enabled:
            reasons.append("live_execution_disabled")
        if ExecutionGateway.status is ExecutionStatus.DISABLED:
            reasons.append("execution_gateway_disabled")

        return PromotionResult(
            PromotionState.LIVE_READY if not reasons else PromotionState.BLOCKED,
            tuple(reasons),
        )
