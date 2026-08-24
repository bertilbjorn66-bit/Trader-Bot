from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.models import Quote
from trader_bot.paper_eval import PaperEvaluationSpec
from trader_bot.paper_session import PaperSession, PaperSessionState
from trader_bot.safety import SafetyState


def quote(bid: str, ask: str, minute: int = 0) -> Quote:
    return Quote(
        timestamp=datetime(2026, 8, 25, 10, minute, tzinfo=timezone.utc),
        instrument=1,
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def decision() -> Decision:
    return Decision(
        action=Action.BUY,
        confidence=0.8,
        reason="paper-session test signal",
        evidence_samples=250,
    )


def safety() -> SafetyState:
    return SafetyState(
        live_trading_enabled=True,
        emergency_stop=False,
        stale_data=False,
        spread_ok=True,
        daily_loss_limit_hit=False,
    )


def spec() -> PaperEvaluationSpec:
    return PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-reference-1",
        minimum_closed_trades=1,
        maximum_session_loss=Decimal("-1"),
    )


def session() -> PaperSession:
    return PaperSession(
        session_id="paper-2026-08-25-001",
        spec=spec(),
        started_at=quote("1.1000", "1.1002").timestamp,
    )


def test_session_starts_open_and_freezes_spec_fingerprint() -> None:
    paper = session()
    report = paper.report()

    assert paper.state == PaperSessionState.OPEN
    assert report.state == PaperSessionState.OPEN
    assert report.finalized_at is None
    assert report.spec_fingerprint == spec().fingerprint()
    assert report.recorded_events == 0
    assert report.evaluation is None


def test_session_records_and_finalizes_once() -> None:
    paper = session()
    opened = paper.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002"),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safety(),
    )
    paper.close_order(opened.order_id, quote("1.1012", "1.1014", minute=1))

    finalized_at = quote("1.1012", "1.1014", minute=2).timestamp
    result = paper.finalize(finalized_at)

    assert paper.state == PaperSessionState.FINALIZED
    assert result.passed is True
    report = paper.report()
    assert report.finalized_at == finalized_at
    assert report.recorded_events == 1
    assert report.evaluation == result


def test_finalization_cannot_precede_session_start() -> None:
    paper = session()
    with pytest.raises(ValueError, match="cannot precede"):
        paper.finalize(paper.started_at - timedelta(seconds=1))


def test_finalized_session_rejects_new_events_and_repeat_finalization() -> None:
    paper = session()
    opened = paper.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002"),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safety(),
    )
    paper.close_order(opened.order_id, quote("1.1012", "1.1014", minute=1))
    paper.finalize(quote("1.1012", "1.1014", minute=2).timestamp)

    with pytest.raises(RuntimeError, match="already finalized"):
        paper.record_signal(
            decision=decision(),
            quote=quote("1.1000", "1.1002", minute=3),
            quantity=Decimal("1"),
            stop_distance=Decimal("0.0010"),
            target_distance=Decimal("0.0020"),
            safety=safety(),
        )

    with pytest.raises(RuntimeError, match="already finalized"):
        paper.finalize(quote("1.1012", "1.1014", minute=3).timestamp)


def test_session_id_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="session_id must be non-empty"):
        PaperSession(session_id=" ", spec=spec(), started_at=quote("1.1000", "1.1002").timestamp)
