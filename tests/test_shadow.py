from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.models import Quote
from trader_bot.shadow import ShadowOnlyLedger

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def quote() -> Quote:
    return Quote(
        timestamp=NOW,
        instrument=1,
        bid=Decimal("1.1000"),
        ask=Decimal("1.1002"),
    )


def decision(action: Action = Action.BUY) -> Decision:
    return Decision(action, 0.8, "validated", 250)


def ledger() -> ShadowOnlyLedger:
    return ShadowOnlyLedger(
        factory_fingerprint="1" * 64,
        safety_fingerprint="2" * 64,
    )


def test_buy_intent_is_recorded_without_transmission() -> None:
    shadow = ledger()
    record = shadow.record(
        decision=decision(),
        quote=quote(),
        quantity=Decimal("1"),
        timestamp=NOW,
    )
    assert record is not None
    assert record.action is Action.BUY
    shadow.verify()
    assert shadow.head_hash != "0" * 64


def test_no_trade_does_not_create_shadow_intent() -> None:
    shadow = ledger()
    assert shadow.record(
        decision=decision(Action.NO_TRADE),
        quote=quote(),
        quantity=Decimal("1"),
        timestamp=NOW,
    ) is None
    assert shadow.records == ()


def test_tampering_breaks_shadow_chain() -> None:
    shadow = ledger()
    record = shadow.record(
        decision=decision(),
        quote=quote(),
        quantity=Decimal("1"),
        timestamp=NOW,
    )
    assert record is not None
    shadow._records[0] = record.__class__(**{**record.__dict__, "quantity": Decimal("2")})
    with pytest.raises(ValueError, match="record hash mismatch"):
        shadow.verify()


def test_non_timezone_timestamp_rejected() -> None:
    shadow = ledger()
    with pytest.raises(ValueError, match="timezone-aware"):
        shadow.record(
            decision=decision(),
            quote=quote(),
            quantity=Decimal("1"),
            timestamp=datetime(2026, 8, 25, 12, 0),
        )
