from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from .decision import Decision
from .models import Quote
from .paper import PaperOrder
from .paper_eval import PaperEvaluationResult, PaperEvaluationSpec
from .paper_evidence import PaperEvidenceJournal
from .paper_session import PaperSession, PaperSessionReport
from .safety import SafetyState


class EvidenceBackedPaperSession:
    """Paper session whose lifecycle events are captured in a hash-chained journal."""

    def __init__(self, *, session_id: str, spec: PaperEvaluationSpec, started_at: datetime) -> None:
        self.session = PaperSession(session_id=session_id, spec=spec, started_at=started_at)
        self.evidence = PaperEvidenceJournal(session_id=session_id, spec_fingerprint=spec.fingerprint())

    @property
    def state(self):
        return self.session.state

    @property
    def orders(self) -> Sequence[PaperOrder]:
        return self.session.orders

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
        order = self.session.record_signal(
            decision=decision,
            quote=quote,
            quantity=quantity,
            stop_distance=stop_distance,
            target_distance=target_distance,
            safety=safety,
            slippage=slippage,
        )
        self.evidence.append_signal(order)
        self.evidence.append_order(order)
        return order

    def close_order(self, order_id: int, quote: Quote, *, slippage: Decimal = Decimal("0")) -> PaperOrder:
        order = self.session.close_order(order_id, quote, slippage=slippage)
        self.evidence.append_order(order)
        return order

    def finalize(self, finalized_at: datetime) -> PaperEvaluationResult:
        result = self.session.finalize(finalized_at)
        self.evidence.finalize(finalized_at)
        self.evidence.verify()
        return result

    def report(self) -> PaperSessionReport:
        return self.session.report()
