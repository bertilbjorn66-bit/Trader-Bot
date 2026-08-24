from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from time import monotonic

from .decision import Action, Decision
from .execution import ExecutionGateway, ExecutionStatus
from .models import Quote
from .safety import SafetyState, authorize_live_action


class PaperEvent(StrEnum):
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class PaperOrder:
    order_id: int
    timestamp: datetime
    instrument: int
    action: Action
    quantity: Decimal
    entry_price: Decimal | None
    stop_distance: Decimal
    target_distance: Decimal
    confidence: float
    evidence_samples: int
    event: PaperEvent
    reason: str
    spread: Decimal
    latency_ms: float
    slippage: Decimal
    exit_price: Decimal | None = None
    pnl: Decimal | None = None


@dataclass
class PaperLedger:
    """Non-transmitting paper ledger that cannot become a broker adapter."""

    orders: list[PaperOrder] = field(default_factory=list)
    _next_id: int = 1

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
        if ExecutionGateway.status != ExecutionStatus.DISABLED:
            raise RuntimeError("Paper ledger refuses to operate unless live execution is disabled")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if stop_distance <= 0 or target_distance <= 0:
            raise ValueError("stop_distance and target_distance must be positive")
        if slippage < 0:
            raise ValueError("slippage must be non-negative")

        started = monotonic()
        state = safety or SafetyState()
        authorized_action = authorize_live_action(decision, state)
        latency_ms = (monotonic() - started) * 1000
        spread = quote.ask - quote.bid

        if authorized_action not in (Action.BUY, Action.SELL):
            order = PaperOrder(
                order_id=self._allocate_id(),
                timestamp=quote.timestamp,
                instrument=quote.instrument,
                action=decision.action,
                quantity=quantity,
                entry_price=None,
                stop_distance=stop_distance,
                target_distance=target_distance,
                confidence=decision.confidence,
                evidence_samples=decision.evidence_samples,
                event=PaperEvent.REJECTED,
                reason="Safety gate rejected the intended action; no broker transmission occurred.",
                spread=spread,
                latency_ms=latency_ms,
                slippage=slippage,
            )
        else:
            entry_price = (
                quote.ask + slippage if authorized_action == Action.BUY else quote.bid - slippage
            )
            order = PaperOrder(
                order_id=self._allocate_id(),
                timestamp=quote.timestamp,
                instrument=quote.instrument,
                action=authorized_action,
                quantity=quantity,
                entry_price=entry_price,
                stop_distance=stop_distance,
                target_distance=target_distance,
                confidence=decision.confidence,
                evidence_samples=decision.evidence_samples,
                event=PaperEvent.FILLED,
                reason="Hypothetical paper fill; no broker transmission occurred.",
                spread=spread,
                latency_ms=latency_ms,
                slippage=slippage,
            )

        self.orders.append(order)
        return order

    def close(
        self,
        order_id: int,
        quote: Quote,
        *,
        slippage: Decimal = Decimal("0"),
    ) -> PaperOrder:
        if ExecutionGateway.status != ExecutionStatus.DISABLED:
            raise RuntimeError("Paper ledger refuses to operate unless live execution is disabled")
        if slippage < 0:
            raise ValueError("slippage must be non-negative")

        current = self._find(order_id)
        if current.event != PaperEvent.FILLED or current.entry_price is None:
            raise ValueError("only an open hypothetical fill can be closed")
        if current.instrument != quote.instrument:
            raise ValueError("quote instrument does not match the paper order")

        exit_price = (
            quote.bid - slippage if current.action == Action.BUY else quote.ask + slippage
        )
        direction = Decimal("1") if current.action == Action.BUY else Decimal("-1")
        pnl = (exit_price - current.entry_price) * current.quantity * direction
        closed = replace(
            current,
            event=PaperEvent.CLOSED,
            exit_price=exit_price,
            pnl=pnl,
            slippage=current.slippage + slippage,
        )
        self.orders = [closed if item.order_id == order_id else item for item in self.orders]
        return closed

    def _allocate_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def _find(self, order_id: int) -> PaperOrder:
        for order in self.orders:
            if order.order_id == order_id:
                return order
        raise KeyError(f"Unknown paper order: {order_id}")
