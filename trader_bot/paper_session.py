from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Sequence

from .decision import Decision
from .models import Quote
from .paper import PaperLedger, PaperOrder
from .paper_eval import PaperEvaluationResult, PaperEvaluationSpec, PaperEvaluator
from .safety import SafetyState


class PaperSessionState(StrEnum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


@dataclass(frozen=True)
class PaperSessionReport:
    session_id: str
    state: PaperSessionState
    started_at: datetime
    finalized_at: datetime | None
    spec_fingerprint: str
    recorded_events: int
    evaluation: PaperEvaluationResult | None


class PaperSession:
    """Lifecycle wrapper for one frozen, non-transmitting paper evaluation."""

    def __init__(
        self,
        *,
        session_id: str,
        spec: PaperEvaluationSpec,
        started_at: datetime,
        ledger: PaperLedger | None = None,
    ) -> None:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        self.session_id = session_id
        self.spec = spec
        self.started_at = started_at
        self._ledger = ledger or PaperLedger()
        self._evaluator = PaperEvaluator(spec)
        self._state = PaperSessionState.OPEN
        self._finalized_at: datetime | None = None
        self._report: PaperEvaluationResult | None = None

    @property
    def state(self) -> PaperSessionState:
        return self._state

    @property
    def orders(self) -> Sequence[PaperOrder]:
        return tuple(self._ledger.orders)

    def record_signal(
        self,
        *,
        decision: Decision,
        quote: Quote,
        quantity: Decimal,
        stop_distance: Decimal,
        target_distance: Decimal,
        safety: SafetyState | None = None,
        slippage: Decimal = Decimal("0"),
    ) -> PaperOrder:
        self._require_open()
        return self._ledger.record_signal(
            decision=decision,
            quote=quote,
            quantity=quantity,
            stop_distance=stop_distance,
            target_distance=target_distance,
            safety=safety,
            slippage=slippage,
        )

    def close_order(
        self,
        order_id: int,
        quote: Quote,
        *,
        slippage: Decimal = Decimal("0"),
    ) -> PaperOrder:
        self._require_open()
        return self._ledger.close(order_id, quote, slippage=slippage)

    def finalize(self, finalized_at: datetime) -> PaperEvaluationResult:
        self._require_open()
        if finalized_at < self.started_at:
            raise ValueError("finalized_at cannot precede started_at")
        result = self._evaluator.evaluate(self._ledger.orders)
        self._report = result
        self._finalized_at = finalized_at
        self._state = PaperSessionState.FINALIZED
        return result

    def report(self) -> PaperSessionReport:
        return PaperSessionReport(
            session_id=self.session_id,
            state=self._state,
            started_at=self.started_at,
            finalized_at=self._finalized_at,
            spec_fingerprint=self._evaluator.spec.fingerprint(),
            recorded_events=len(self._ledger.orders),
            evaluation=self._report,
        )

    def _require_open(self) -> None:
        if self._state != PaperSessionState.OPEN:
            raise RuntimeError("paper session is already finalized")
