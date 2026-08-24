from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.models import Quote
from trader_bot.paper import PaperLedger
from trader_bot.paper_evidence import EvidenceKind, PaperEvidenceJournal
from trader_bot.paper_eval import PaperEvaluationSpec
from trader_bot.safety import SafetyState


def quote(bid: str, ask: str, minute: int = 0) -> Quote:
    return Quote(
        timestamp=datetime(2026, 8, 25, 10, minute, tzinfo=timezone.utc),
        instrument=1,
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def decision() -> Decision:
    return Decision(Action.BUY, 0.8, "evidence test signal", 250)


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


def filled_order():
    ledger = PaperLedger()
    return ledger.record_signal(
        decision=decision(),
        quote=quote("1.1000", "1.1002"),
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
        safety=safety(),
    )


def test_empty_journal_has_genesis_hash() -> None:
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    assert journal.head_hash == "0" * 64
    assert journal.records == ()
    journal.verify()


def test_hash_chain_is_deterministic_and_verifiable() -> None:
    order = filled_order()
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    first = journal.append_order(order)
    final = journal.finalize(order.timestamp + timedelta(minutes=1))

    journal.verify()
    assert first.sequence == 1
    assert final.sequence == 2
    assert final.kind == EvidenceKind.FINALIZED
    assert journal.head_hash == final.record_hash
    assert journal.to_json() == journal.to_json()


def test_tampering_is_detected() -> None:
    order = filled_order()
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    record = journal.append_order(order)
    journal._records[0] = record.__class__(
        sequence=record.sequence,
        timestamp=record.timestamp,
        kind=record.kind,
        session_id=record.session_id,
        spec_fingerprint=record.spec_fingerprint,
        order_id=record.order_id,
        event=record.event,
        instrument=record.instrument,
        action=record.action,
        quantity=record.quantity,
        price=Decimal("999"),
        spread=record.spread,
        slippage=record.slippage,
        latency_ms=record.latency_ms,
        pnl=record.pnl,
        reason=record.reason,
        previous_hash=record.previous_hash,
        record_hash=record.record_hash,
    )

    with pytest.raises(ValueError, match="record hash mismatch"):
        journal.verify()


def test_out_of_order_events_are_rejected() -> None:
    order = filled_order()
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    journal.append_order(order)

    with pytest.raises(ValueError, match="chronological"):
        journal.finalize(order.timestamp - timedelta(seconds=1))


def test_finalized_journal_rejects_more_records() -> None:
    order = filled_order()
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    journal.append_order(order)
    journal.finalize(order.timestamp + timedelta(minutes=1))

    with pytest.raises(RuntimeError, match="already finalized"):
        journal.append_order(order)

    with pytest.raises(RuntimeError, match="already finalized"):
        journal.finalize(order.timestamp + timedelta(minutes=2))


def test_fingerprint_mismatch_is_detected() -> None:
    order = filled_order()
    journal = PaperEvidenceJournal(session_id="paper-1", spec_fingerprint=spec().fingerprint())
    journal.append_order(order)
    journal.spec_fingerprint = "tampered"

    with pytest.raises(ValueError, match="specification fingerprint mismatch"):
        journal.verify()
