from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .paper import PaperEvent, PaperOrder


@dataclass(frozen=True)
class PaperEvaluationSpec:
    """Immutable evaluation contract for one paper/shadow session."""

    strategy_id: str
    strategy_version: str
    research_reference: str
    maximum_session_loss: Decimal
    minimum_closed_trades: int = 100

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("strategy_id must be non-empty")
        if not self.strategy_version.strip():
            raise ValueError("strategy_version must be non-empty")
        if not self.research_reference.strip():
            raise ValueError("research_reference must be non-empty")
        if self.maximum_session_loss >= 0:
            raise ValueError("maximum_session_loss must be negative")
        if self.minimum_closed_trades <= 0:
            raise ValueError("minimum_closed_trades must be positive")

    def fingerprint(self) -> str:
        payload = {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "research_reference": self.research_reference,
            "maximum_session_loss": str(self.maximum_session_loss),
            "minimum_closed_trades": self.minimum_closed_trades,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PaperEvaluationResult:
    spec_fingerprint: str
    closed_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: Decimal
    expectancy: Decimal
    profit_factor: Decimal | None
    max_drawdown: Decimal
    passed: bool
    failure_reasons: tuple[str, ...]


class PaperEvaluator:
    """Produces a deterministic evaluation from closed hypothetical paper trades."""

    def __init__(self, spec: PaperEvaluationSpec) -> None:
        self.spec = spec
        self._fingerprint = spec.fingerprint()

    def evaluate(self, orders: Sequence[PaperOrder]) -> PaperEvaluationResult:
        if self.spec.fingerprint() != self._fingerprint:
            raise RuntimeError("Paper evaluation specification changed after session start")

        closed = [order for order in orders if order.event == PaperEvent.CLOSED]
        seen_ids: set[int] = set()
        previous_timestamp = None
        for order in closed:
            if order.order_id in seen_ids:
                raise ValueError("duplicate closed paper order id")
            seen_ids.add(order.order_id)
            if previous_timestamp is not None and order.timestamp < previous_timestamp:
                raise ValueError("closed paper orders must be chronological")
            previous_timestamp = order.timestamp
            if order.pnl is None:
                raise ValueError("closed paper order is missing P&L")

        pnl = [order.pnl for order in closed if order.pnl is not None]
        total_pnl = sum(pnl, Decimal("0"))
        winning_trades = sum(value > 0 for value in pnl)
        losing_trades = sum(value < 0 for value in pnl)
        gross_profit = sum((value for value in pnl if value > 0), Decimal("0"))
        gross_loss = -sum((value for value in pnl if value < 0), Decimal("0"))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
        expectancy = total_pnl / len(pnl) if pnl else Decimal("0")

        equity = Decimal("0")
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        for value in pnl:
            equity += value
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        failures: list[str] = []
        if len(pnl) < self.spec.minimum_closed_trades:
            failures.append("minimum_closed_trades_not_met")
        if total_pnl <= self.spec.maximum_session_loss:
            failures.append("maximum_session_loss_breached")
        if not pnl:
            failures.append("no_closed_trades")

        return PaperEvaluationResult(
            spec_fingerprint=self._fingerprint,
            closed_trades=len(pnl),
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            expectancy=expectancy,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            passed=not failures,
            failure_reasons=tuple(failures),
        )
