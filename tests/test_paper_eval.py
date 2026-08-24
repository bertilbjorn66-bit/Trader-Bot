from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.models import Quote
from trader_bot.paper import PaperLedger, PaperOrder
from trader_bot.paper_eval import PaperEvaluationSpec, PaperEvaluator
from trader_bot.safety import SafetyState


def quote(bid: str, ask: str, instrument: int = 1, minute: int = 0) -> Quote:
    return Quote(
        timestamp=datetime(2026, 8, 25, 10, minute, tzinfo=timezone.utc),
        instrument=instrument,
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def decision() -> Decision:
    return Decision(
        action=Action.BUY,
        confidence=0.75,
        reason="frozen paper test signal",
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


def build_closed_orders() -> list[PaperOrder]:
    ledger = PaperLedger()
    opened = ledger.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002", minute=0),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safe_state(),
    )
    closed = ledger.close(opened.order_id, quote("1.1012", "1.1014", minute=1))
    return [closed]


def test_spec_fingerprint_is_stable() -> None:
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
    )
    assert spec.fingerprint() == spec.fingerprint()
    assert len(spec.fingerprint()) == 64


def test_evaluator_requires_minimum_sample_and_reports_metrics() -> None:
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
        minimum_closed_trades=2,
        maximum_session_loss=Decimal("-1"),
    )
    result = PaperEvaluator(spec).evaluate(build_closed_orders())

    assert result.closed_trades == 1
    assert result.winning_trades == 1
    assert result.losing_trades == 0
    assert result.total_pnl == Decimal("0.0010")
    assert result.expectancy == Decimal("0.0010")
    assert result.profit_factor is None
    assert result.max_drawdown == Decimal("0")
    assert result.passed is False
    assert result.failure_reasons == ("minimum_closed_trades_not_met",)


def test_evaluator_reports_profit_factor_and_drawdown_deterministically() -> None:
    base = build_closed_orders()[0]
    second = replace(
        base,
        order_id=2,
        timestamp=base.timestamp + timedelta(minutes=1),
        pnl=Decimal("-0.0004"),
    )
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
        minimum_closed_trades=2,
        maximum_session_loss=Decimal("-1"),
    )

    result = PaperEvaluator(spec).evaluate([base, second])

    assert result.closed_trades == 2
    assert result.winning_trades == 1
    assert result.losing_trades == 1
    assert result.total_pnl == Decimal("0.0006")
    assert result.expectancy == Decimal("0.0003")
    assert result.profit_factor == Decimal("2.5")
    assert result.max_drawdown == Decimal("0.0004")
    assert result.passed is True


def test_evaluator_rejects_missing_pnl() -> None:
    orders = build_closed_orders()
    broken = replace(orders[0], pnl=None)
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
    )

    with pytest.raises(ValueError, match="missing P&L"):
        PaperEvaluator(spec).evaluate([broken])


def test_evaluator_detects_spec_mutation() -> None:
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
    )
    evaluator = PaperEvaluator(spec)
    object.__setattr__(spec, "strategy_version", "2")

    with pytest.raises(RuntimeError, match="specification changed"):
        evaluator.evaluate([])


def test_session_loss_limit_is_enforced() -> None:
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
        minimum_closed_trades=1,
        maximum_session_loss=Decimal("-0.0005"),
    )
    ledger = PaperLedger()
    opened = ledger.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002", minute=0),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safe_state(),
    )
    closed = ledger.close(opened.order_id, quote("1.0990", "1.0992", minute=1))

    result = PaperEvaluator(spec).evaluate([closed])
    assert result.passed is False
    assert "maximum_session_loss_breached" in result.failure_reasons


def test_duplicate_closed_orders_are_rejected() -> None:
    order = build_closed_orders()[0]
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
    )

    with pytest.raises(ValueError, match="duplicate closed paper order id"):
        PaperEvaluator(spec).evaluate([order, order])


def test_out_of_order_closed_orders_are_rejected() -> None:
    order = build_closed_orders()[0]
    earlier = replace(order, order_id=2, timestamp=order.timestamp - timedelta(minutes=1))
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
    )

    with pytest.raises(ValueError, match="must be chronological"):
        PaperEvaluator(spec).evaluate([order, earlier])
