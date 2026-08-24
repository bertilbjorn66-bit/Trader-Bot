from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.execution import ExecutionGateway, ExecutionStatus
from trader_bot.models import Quote
from trader_bot.paper import PaperEvent, PaperLedger
from trader_bot.safety import SafetyState


def quote(price_bid: str, price_ask: str) -> Quote:
    return Quote(
        timestamp=datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
        instrument=1,
        bid=Decimal(price_bid),
        ask=Decimal(price_ask),
    )


def decision(action: Action = Action.BUY) -> Decision:
    return Decision(
        action=action,
        confidence=0.75,
        reason="validated signal",
        evidence_samples=250,
    )


def safe_state() -> SafetyState:
    return SafetyState(
        live_trading_enabled=True,
        emergency_stop=False,
        stale_data=False,
        spread_ok=True,
        daily_loss_limit_hit=False,
    )


def test_default_safety_rejects_without_transmission() -> None:
    assert ExecutionGateway.status == ExecutionStatus.DISABLED
    ledger = PaperLedger()

    order = ledger.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002"),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
    )

    assert order.event == PaperEvent.REJECTED
    assert order.entry_price is None
    assert "no broker transmission" in order.reason.lower()


def test_paper_fill_and_close_track_spread_slippage_and_pnl() -> None:
    assert ExecutionGateway.status == ExecutionStatus.DISABLED
    ledger = PaperLedger()

    opened = ledger.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002"),
        quantity=Decimal("2"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safe_state(),
        slippage=Decimal("0.0001"),
    )
    assert opened.event == PaperEvent.FILLED
    assert opened.entry_price == Decimal("1.1003")
    assert opened.spread == Decimal("0.0002")

    closed = ledger.close(
        opened.order_id,
        quote("1.1012", "1.1014"),
        slippage=Decimal("0.0001"),
    )
    assert closed.event == PaperEvent.CLOSED
    assert closed.exit_price == Decimal("1.1011")
    assert closed.pnl == Decimal("0.0016")
    assert closed.slippage == Decimal("0.0002")


def test_paper_ledger_refuses_if_execution_is_not_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ExecutionGateway, "status", ExecutionStatus.NOT_IMPLEMENTED)

    with pytest.raises(RuntimeError, match="live execution is disabled"):
        PaperLedger().record_signal(
            decision=decision(),
            quote=quote("1.1000", "1.1002"),
            quantity=Decimal("1"),
            stop_distance=Decimal("0.0010"),
            target_distance=Decimal("0.0020"),
        )
