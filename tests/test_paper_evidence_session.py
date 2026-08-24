from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.models import Quote
from trader_bot.paper_evidence_session import EvidenceBackedPaperSession
from trader_bot.paper_eval import PaperEvaluationSpec
from trader_bot.paper_session import PaperSessionState
from trader_bot.safety import SafetyState


def quote(bid: str, ask: str, minute: int = 0) -> Quote:
    return Quote(
        timestamp=datetime(2026, 8, 25, 10, minute, tzinfo=timezone.utc),
        instrument=1,
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def spec() -> PaperEvaluationSpec:
    return PaperEvaluationSpec(
        strategy_id="candidate-a",
        strategy_version="1",
        research_reference="frozen-reference-1",
        minimum_closed_trades=1,
        maximum_session_loss=Decimal("-1"),
    )


def decision() -> Decision:
    return Decision(Action.BUY, 0.8, "evidence-backed test signal", 250)


def safety() -> SafetyState:
    return SafetyState(
        live_trading_enabled=True,
        emergency_stop=False,
        stale_data=False,
        spread_ok=True,
        daily_loss_limit_hit=False,
    )


def make_session() -> EvidenceBackedPaperSession:
    return EvidenceBackedPaperSession(
        session_id="paper-evidence-001",
        spec=spec(),
        started_at=quote("1.1000", "1.1002").timestamp,
    )


def test_session_and_evidence_share_frozen_fingerprint() -> None:
    paper = make_session()
    assert paper.evidence.spec_fingerprint == spec().fingerprint()
    assert paper.report().state == PaperSessionState.OPEN


def test_signal_and_close_are_automatically_journaled() -> None:
    paper = make_session()
    opened = paper.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002"),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safety(),
    )
    paper.close_order(opened.order_id, quote("1.1012", "1.1014", minute=1))

    kinds = [record.kind.value for record in paper.evidence.records]
    assert kinds == ["SIGNAL", "ORDER", "CLOSE"]
    paper.evidence.verify()


def test_finalize_is_recorded_and_is_terminal() -> None:
    paper = make_session()
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

    assert paper.state == PaperSessionState.FINALIZED
    assert paper.evidence.records[-1].kind.value == "FINALIZED"
    paper.evidence.verify()

    with pytest.raises(RuntimeError, match="already finalized"):
        paper.record_signal(
            decision=decision(),
            quote=quote("1.1000", "1.1002", minute=3),
            quantity=Decimal("1"),
            stop_distance=Decimal("0.0010"),
            target_distance=Decimal("0.0020"),
            safety=safety(),
        )
