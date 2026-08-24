from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.models import Quote
from trader_bot.paper_eval import PaperEvaluationSpec
from trader_bot.paper_evidence_session import EvidenceBackedPaperSession
from trader_bot.paper_session import PaperSessionState
from trader_bot.safety import SafetyState


def quote(bid: str, ask: str, minute: int = 0) -> Quote:
    return Quote(
        timestamp=datetime(2026, 8, 25, 10, minute, tzinfo=timezone.utc),
        instrument=1,
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def make_session() -> EvidenceBackedPaperSession:
    return EvidenceBackedPaperSession(
        session_id="paper-evidence-001",
        spec=PaperEvaluationSpec("candidate-a", "1", "frozen-reference-1", Decimal("-1"), 1),
        started_at=quote("1.1000", "1.1002").timestamp,
    )


def decision() -> Decision:
    return Decision(Action.BUY, 0.8, "evidence-backed signal", 250)


def safety() -> SafetyState:
    return SafetyState(True, False, False, True, False)


def test_events_are_captured_automatically() -> None:
    paper = make_session()
    opened = paper.record_signal(decision=decision(), quote=quote("1.1000", "1.1002"), quantity=Decimal("1"), stop_distance=Decimal("0.0010"), target_distance=Decimal("0.0020"), safety=safety())
    paper.close_order(opened.order_id, quote("1.1012", "1.1014", 1))
    assert [r.kind.value for r in paper.evidence.records] == ["SIGNAL", "ORDER", "CLOSE"]
    paper.evidence.verify()


def test_finalize_adds_terminal_evidence() -> None:
    paper = make_session()
    opened = paper.record_signal(decision=decision(), quote=quote("1.1000", "1.1002"), quantity=Decimal("1"), stop_distance=Decimal("0.0010"), target_distance=Decimal("0.0020"), safety=safety())
    paper.close_order(opened.order_id, quote("1.1012", "1.1014", 1))
    result = paper.finalize(quote("1.1012", "1.1014", 2).timestamp)
    assert result.passed
    assert paper.state == PaperSessionState.FINALIZED
    assert paper.evidence.records[-1].kind.value == "FINALIZED"
    paper.evidence.verify()
    with pytest.raises(RuntimeError, match="already finalized"):
        paper.record_signal(decision=decision(), quote=quote("1.1000", "1.1002", 3), quantity=Decimal("1"), stop_distance=Decimal("0.0010"), target_distance=Decimal("0.0020"), safety=safety())
