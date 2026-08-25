from trader_bot.decision_factory import FactoryState
from trader_bot.execution import ExecutionGateway
from trader_bot.final_promotion import FinalPromotionGate, PromotionInputs, PromotionState


def base_inputs() -> PromotionInputs:
    return PromotionInputs(
        empirical_confirmation_passed=False,
        robustness_passed=False,
        factory_state=FactoryState.BLOCKED,
        paper_passed=False,
        shadow_passed=False,
        credentials_configured=False,
        emergency_stop_tested=False,
        daily_loss_tested=False,
        stale_spread_tested=False,
        broker_limits_verified=False,
        human_approval_present=False,
    )


def test_current_state_is_blocked_by_research_and_factory() -> None:
    result = FinalPromotionGate().evaluate(base_inputs())
    assert result.state is PromotionState.BLOCKED
    assert "strategy_factory_not_eligible" in result.reasons
    assert ExecutionGateway.status.value == "DISABLED"


def test_paper_ready_after_pre_paper_gates() -> None:
    inputs = PromotionInputs(
        **{**base_inputs().__dict__, "empirical_confirmation_passed": True, "robustness_passed": True, "factory_state": FactoryState.ELIGIBLE}
    )
    result = FinalPromotionGate().evaluate(inputs)
    assert result.state is PromotionState.PAPER_READY
    assert result.reasons == ("paper_period_not_passed",)


def test_shadow_ready_after_paper() -> None:
    inputs = PromotionInputs(
        **{
            **base_inputs().__dict__,
            "empirical_confirmation_passed": True,
            "robustness_passed": True,
            "factory_state": FactoryState.ELIGIBLE,
            "paper_passed": True,
        }
    )
    result = FinalPromotionGate().evaluate(inputs)
    assert result.state is PromotionState.SHADOW_READY
    assert result.reasons == ("shadow_period_not_passed",)


def test_live_can_never_be_ready_while_gateway_disabled() -> None:
    inputs = PromotionInputs(
        **{
            **base_inputs().__dict__,
            "empirical_confirmation_passed": True,
            "robustness_passed": True,
            "factory_state": FactoryState.ELIGIBLE,
            "paper_passed": True,
            "shadow_passed": True,
            "credentials_configured": True,
            "emergency_stop_tested": True,
            "daily_loss_tested": True,
            "stale_spread_tested": True,
            "broker_limits_verified": True,
            "human_approval_present": True,
            "live_execution_enabled": True,
        }
    )
    result = FinalPromotionGate().evaluate(inputs)
    assert result.state is PromotionState.BLOCKED
    assert "execution_gateway_disabled" in result.reasons
