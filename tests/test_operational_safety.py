from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.operational_safety import (
    CredentialPolicy,
    HumanApproval,
    OperationalSafety,
    OperationalSafetySpec,
    SafetyState,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def spec() -> OperationalSafetySpec:
    return OperationalSafetySpec(
        maximum_daily_loss=Decimal("-100"),
        maximum_quote_age=timedelta(seconds=5),
        maximum_spread=Decimal("0.0005"),
    )


def test_paper_ready_after_reset_with_healthy_quote() -> None:
    safety = OperationalSafety(spec())
    safety.reset_for_paper_session()
    safety.verify_paper_ready(
        now=NOW,
        quote_timestamp=NOW - timedelta(seconds=1),
        spread=Decimal("0.0002"),
    )


def test_stale_quote_blocks_paper() -> None:
    safety = OperationalSafety(spec())
    safety.reset_for_paper_session()
    result = safety.evaluate(
        now=NOW,
        quote_timestamp=NOW - timedelta(seconds=6),
        spread=Decimal("0.0002"),
    )
    assert result.state is SafetyState.BLOCKED
    assert "quote_stale" in result.reasons


def test_wide_spread_blocks_paper() -> None:
    safety = OperationalSafety(spec())
    safety.reset_for_paper_session()
    result = safety.evaluate(
        now=NOW,
        quote_timestamp=NOW - timedelta(seconds=1),
        spread=Decimal("0.0006"),
    )
    assert result.state is SafetyState.BLOCKED
    assert "spread_limit_breached" in result.reasons


def test_daily_loss_triggers_emergency_stop() -> None:
    safety = OperationalSafety(spec())
    safety.reset_for_paper_session()
    safety.record_pnl(Decimal("-100"))
    assert safety.emergency_stopped
    assert safety.daily_pnl == Decimal("-100")


def test_emergency_stop_clears_approval() -> None:
    safety = OperationalSafety(spec())
    approval = HumanApproval("approval-1", spec().fingerprint(), NOW)
    safety.set_human_approval(approval)
    safety.trigger_emergency_stop()
    live = safety.evaluate_live()
    assert live.state is SafetyState.BLOCKED
    assert "human_approval_missing" in live.reasons


def test_live_authorization_remains_blocked_even_with_approval() -> None:
    safety = OperationalSafety(spec())
    safety.reset_for_paper_session()
    safety.set_human_approval(HumanApproval("approval-1", spec().fingerprint(), NOW))
    safety.verify_live_remains_blocked()


def test_wrong_approval_fingerprint_is_rejected() -> None:
    safety = OperationalSafety(spec())
    with pytest.raises(ValueError, match="fingerprint"):
        safety.set_human_approval(HumanApproval("approval-1", "0" * 64, NOW))


def test_mutated_spec_is_detected() -> None:
    safety_spec = spec()
    safety = OperationalSafety(safety_spec)
    object.__setattr__(safety_spec, "maximum_spread", Decimal("0.001"))
    with pytest.raises(RuntimeError, match="specification changed"):
        safety.evaluate(now=NOW, quote_timestamp=NOW, spread=Decimal("0"))


def test_credential_policy_requires_runtime_secrets_and_rejects_source_literals() -> None:
    policy = CredentialPolicy(
        required_secret_names=("BROKER_API_KEY", "BROKER_API_SECRET"),
        forbidden_source_literals=("hard-coded-secret",),
    )
    policy.validate_environment({"BROKER_API_KEY": "x", "BROKER_API_SECRET": "y"})
    with pytest.raises(ValueError, match="missing required runtime secrets"):
        policy.validate_environment({"BROKER_API_KEY": "x"})
    with pytest.raises(ValueError, match="forbidden credential literal"):
        policy.validate_source("hard-coded-secret")
