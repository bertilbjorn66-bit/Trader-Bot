from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from os import environ
from types import MappingProxyType


class SafetyState(StrEnum):
    BLOCKED = "BLOCKED"
    READY_FOR_PAPER = "READY_FOR_PAPER"
    READY_FOR_SHADOW = "READY_FOR_SHADOW"


@dataclass(frozen=True)
class OperationalSafetySpec:
    """Immutable operational guardrails for paper/shadow readiness."""

    maximum_daily_loss: Decimal
    maximum_quote_age: timedelta
    maximum_spread: Decimal
    approval_required: bool = True
    live_orders_allowed: bool = False

    def __post_init__(self) -> None:
        if self.maximum_daily_loss >= 0:
            raise ValueError("maximum_daily_loss must be negative")
        if self.maximum_quote_age <= timedelta(0):
            raise ValueError("maximum_quote_age must be positive")
        if self.maximum_spread < Decimal("0"):
            raise ValueError("maximum_spread must be non-negative")
        if self.live_orders_allowed:
            raise ValueError("live_orders_allowed must remain false in Stage 11")

    def fingerprint(self) -> str:
        payload = {
            "maximum_daily_loss": str(self.maximum_daily_loss),
            "maximum_quote_age_seconds": self.maximum_quote_age.total_seconds(),
            "maximum_spread": str(self.maximum_spread),
            "approval_required": self.approval_required,
            "live_orders_allowed": self.live_orders_allowed,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class HumanApproval:
    approval_id: str
    runtime_fingerprint: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if not self.approval_id.strip():
            raise ValueError("approval_id must be non-empty")
        if len(self.runtime_fingerprint) != 64:
            raise ValueError("runtime_fingerprint must be a SHA-256 fingerprint")
        if self.approved_at.tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")


@dataclass(frozen=True)
class CredentialPolicy:
    """Policy describing how secrets are allowed to enter the runtime."""

    required_secret_names: tuple[str, ...]
    forbidden_source_literals: tuple[str, ...]

    def validate_environment(self, environment: Mapping[str, str] | None = None) -> None:
        values = environment if environment is not None else MappingProxyType(dict(environ))
        missing = [name for name in self.required_secret_names if not values.get(name, "").strip()]
        if missing:
            raise ValueError(f"missing required runtime secrets: {', '.join(missing)}")

    def validate_source(self, source_text: str) -> None:
        for literal in self.forbidden_source_literals:
            if literal in source_text:
                raise ValueError(f"forbidden credential literal found: {literal}")


@dataclass(frozen=True)
class SafetyEvaluation:
    state: SafetyState
    reasons: tuple[str, ...]
    spec_fingerprint: str


class OperationalSafety:
    """Runtime safety latch for paper/shadow operation."""

    def __init__(self, spec: OperationalSafetySpec) -> None:
        self.spec = spec
        self._spec_fingerprint = spec.fingerprint()
        self._daily_pnl = Decimal("0")
        self._emergency_stopped = True
        self._approval: HumanApproval | None = None

    @property
    def emergency_stopped(self) -> bool:
        return self._emergency_stopped

    @property
    def daily_pnl(self) -> Decimal:
        return self._daily_pnl

    def reset_for_paper_session(self) -> None:
        self._assert_spec_unchanged()
        self._daily_pnl = Decimal("0")
        self._emergency_stopped = False
        self._approval = None

    def trigger_emergency_stop(self) -> None:
        self._emergency_stopped = True
        self._approval = None

    def record_pnl(self, delta: Decimal) -> None:
        self._assert_spec_unchanged()
        self._daily_pnl += delta
        if self._daily_pnl <= self.spec.maximum_daily_loss:
            self.trigger_emergency_stop()

    def set_human_approval(self, approval: HumanApproval) -> None:
        self._assert_spec_unchanged()
        if approval.runtime_fingerprint != self._spec_fingerprint:
            raise ValueError("human approval fingerprint does not match safety specification")
        self._approval = approval

    def evaluate(self, *, now: datetime, quote_timestamp: datetime, spread: Decimal) -> SafetyEvaluation:
        self._assert_spec_unchanged()
        if now.tzinfo is None or quote_timestamp.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        reasons: list[str] = []
        if self._emergency_stopped:
            reasons.append("emergency_stop_active")
        if self._daily_pnl <= self.spec.maximum_daily_loss:
            reasons.append("daily_loss_limit_breached")
        if now - quote_timestamp > self.spec.maximum_quote_age:
            reasons.append("quote_stale")
        if spread > self.spec.maximum_spread:
            reasons.append("spread_limit_breached")
        if self.spec.live_orders_allowed:
            reasons.append("live_orders_not_allowed")
        return SafetyEvaluation(
            SafetyState.READY_FOR_PAPER if not reasons else SafetyState.BLOCKED,
            tuple(reasons),
            self._spec_fingerprint,
        )

    def evaluate_live(self) -> SafetyEvaluation:
        self._assert_spec_unchanged()
        reasons: list[str] = []
        if self.spec.approval_required and self._approval is None:
            reasons.append("human_approval_missing")
        if self.spec.live_orders_allowed is False:
            reasons.append("live_orders_not_allowed")
        if self._emergency_stopped:
            reasons.append("emergency_stop_active")
        return SafetyEvaluation(
            SafetyState.READY_FOR_SHADOW if not reasons else SafetyState.BLOCKED,
            tuple(reasons),
            self._spec_fingerprint,
        )

    def verify_paper_ready(self, *, now: datetime, quote_timestamp: datetime, spread: Decimal) -> None:
        result = self.evaluate(now=now, quote_timestamp=quote_timestamp, spread=spread)
        if result.state is not SafetyState.READY_FOR_PAPER:
            raise RuntimeError("operational safety is not ready: " + "; ".join(result.reasons))

    def verify_live_remains_blocked(self) -> None:
        result = self.evaluate_live()
        if result.state is not SafetyState.BLOCKED:
            raise AssertionError("Stage 11 unexpectedly permits live authorization")

    def _assert_spec_unchanged(self) -> None:
        if self.spec.fingerprint() != self._spec_fingerprint:
            raise RuntimeError("operational safety specification changed")
