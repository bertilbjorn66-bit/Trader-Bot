from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.models import Quote
from trader_bot.paper import PaperLedger
from trader_bot.paper_eval import PaperEvaluationSpec
from trader_bot.paper_evidence import EvidenceKind, PaperEvidenceJournal
from trader_bot.safety import SafetyState


def quote(bid: str, ask: str, minute: int = 0) -> Quote:
    return Quote(datetime(2026, 8, 25, 10, minute, tzinfo=timezone.utc), 1, Decimal(bid), Decimal(ask))


def spec() -> PaperEvaluationSpec:
    return PaperEvaluationSpec("candidate-a", "1", "frozen-reference-1", Decimal("-1"), 1)


def order():
    return PaperLedger().record_signal(
        decision=Decision(Action.BUY, 0.8, "evidence test signal", 250),
        quote=quote("1.1000", "1.1002"), quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"), target_distance=Decimal("0.0020"),
        safety=SafetyState(True, False, False, True, False),
    )


def test_genesis_and_empty_verify() -> None:
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    assert journal.head_hash == "0" * 64
    journal.verify()


def test_chain_and_finalization_are_verifiable_and_deterministic() -> None:
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    first = journal.append_order(order())
    final = journal.finalize(first.timestamp + timedelta(minutes=1))
    journal.verify()
    assert first.sequence == 1
    assert final.sequence == 2
    assert final.kind == EvidenceKind.FINALIZED
    assert journal.to_json() == journal.to_json()


def test_tampering_breaks_verification() -> None:
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    record = journal.append_order(order())
    journal._records[0] = record.__class__(**{**record.__dict__, "price": Decimal("999")})
    with pytest.raises(ValueError, match="record hash mismatch"):
        journal.verify()


def test_out_of_order_and_post_finalize_events_are_rejected() -> None:
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    record = journal.append_order(order())
    with pytest.raises(ValueError, match="chronological"):
        journal.finalize(record.timestamp - timedelta(seconds=1))
    journal.finalize(record.timestamp + timedelta(minutes=1))
    with pytest.raises(RuntimeError, match="already finalized"):
        journal.append_order(order())
    with pytest.raises(RuntimeError, match="already finalized"):
        journal.finalize(record.timestamp + timedelta(minutes=2))


def test_fingerprint_tampering_is_detected() -> None:
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    journal.append_order(order())
    journal.spec_fingerprint = "tampered"
    with pytest.raises(ValueError, match="specification fingerprint mismatch"):
        journal.verify()
