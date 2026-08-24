from decimal import Decimal

import pytest

from trader_bot.decision import Action
from trader_bot.paper import PaperLedger
from trader_bot.paper_eval import PaperEvaluationSpec, PaperEvaluator
from trader_bot.models import Quote
from trader_bot.safety import SafetyState


def quote(bid: str, ask: str, instrument: int = 1) -> Quote:
    from datetime import datetime, timezone

    return Quote(
        timestamp=datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
        instrument=instrument,
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def decision() -> object:
    from trader_bot.decision import Decision

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


def build_closed_orders() -> list[object]:
    ledger = PaperLedger()
    opened = ledger.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002"),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safe_state(),
    )
    closed = ledger.close(opened.order_id, quote("1.1012", "1.1014"))
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
        maximum_daily_loss=Decimal("-1"),
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


def test_evaluator_rejects_missing_pnl() -> None:
    orders = build_closed_orders()
    from dataclasses import replace

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


def test_negative_loss_limit_is_enforced() -> None:
    spec = PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-confirmation-1",
        minimum_closed_trades=1,
        maximum_daily_loss=Decimal("-0.0005"),
    )
    ledger = PaperLedger()
    opened = ledger.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002"),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safe_state(),
    )
    closed = ledger.close(opened.order_id, quote("1.0990", "1.0992"))

    result = PaperEvaluator(spec).evaluate([closed])
    assert result.passed is True
