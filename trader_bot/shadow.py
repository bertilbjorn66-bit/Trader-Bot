from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .decision import Action, Decision
from .execution import ExecutionGateway, ExecutionStatus
from .models import Quote


@dataclass(frozen=True)
class ShadowIntent:
    sequence: int
    timestamp: datetime
    instrument: int
    action: Action
    quantity: Decimal
    bid: Decimal
    ask: Decimal
    spread: Decimal
    reason: str
    factory_fingerprint: str
    safety_fingerprint: str
    previous_hash: str
    record_hash: str


class ShadowOnlyLedger:
    """Append-only shadow order-intent ledger with no broker transmission path."""

    def __init__(self, *, factory_fingerprint: str, safety_fingerprint: str) -> None:
        if len(factory_fingerprint) != 64 or len(safety_fingerprint) != 64:
            raise ValueError("fingerprints must be SHA-256 values")
        self.factory_fingerprint = factory_fingerprint
        self.safety_fingerprint = safety_fingerprint
        self._records: list[ShadowIntent] = []

    @property
    def records(self) -> Sequence[ShadowIntent]:
        return tuple(self._records)

    @property
    def head_hash(self) -> str:
        return self._records[-1].record_hash if self._records else "0" * 64

    def record(self, *, decision: Decision, quote: Quote, quantity: Decimal, timestamp: datetime) -> ShadowIntent | None:
        if ExecutionGateway.status is not ExecutionStatus.DISABLED:
            raise RuntimeError("shadow ledger requires ExecutionGateway.DISABLED")
        if timestamp.tzinfo is None or quote.timestamp.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if decision.action not in (Action.BUY, Action.SELL):
            return None
        previous_hash = self.head_hash
        intent = ShadowIntent(
            sequence=len(self._records) + 1,
            timestamp=timestamp,
            instrument=quote.instrument,
            action=decision.action,
            quantity=quantity,
            bid=quote.bid,
            ask=quote.ask,
            spread=quote.ask - quote.bid,
            reason=decision.reason,
            factory_fingerprint=self.factory_fingerprint,
            safety_fingerprint=self.safety_fingerprint,
            previous_hash=previous_hash,
            record_hash="",
        )
        intent = ShadowIntent(
            **{**intent.__dict__, "record_hash": self._hash_record(intent, previous_hash)}
        )
        self._records.append(intent)
        return intent

    def verify(self) -> None:
        previous_hash = "0" * 64
        previous_timestamp: datetime | None = None
        for expected, record in enumerate(self._records, start=1):
            if record.sequence != expected:
                raise ValueError("shadow sequence is not contiguous")
            if previous_timestamp is not None and record.timestamp < previous_timestamp:
                raise ValueError("shadow timestamps must be chronological")
            if record.previous_hash != previous_hash:
                raise ValueError("shadow hash chain is broken")
            if record.record_hash != self._hash_record(record, previous_hash):
                raise ValueError("shadow record hash mismatch")
            previous_hash = record.record_hash
            previous_timestamp = record.timestamp

    def to_json(self) -> str:
        self.verify()
        return json.dumps(
            {
                "factory_fingerprint": self.factory_fingerprint,
                "safety_fingerprint": self.safety_fingerprint,
                "head_hash": self.head_hash,
                "records": [self._payload(record) for record in self._records],
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _payload(self, record: ShadowIntent) -> dict[str, object]:
        return {
            "sequence": record.sequence,
            "timestamp": record.timestamp.isoformat(),
            "instrument": record.instrument,
            "action": record.action.value,
            "quantity": str(record.quantity),
            "bid": str(record.bid),
            "ask": str(record.ask),
            "spread": str(record.spread),
            "reason": record.reason,
            "factory_fingerprint": record.factory_fingerprint,
            "safety_fingerprint": record.safety_fingerprint,
            "previous_hash": record.previous_hash,
        }

    def _hash_record(self, record: ShadowIntent, previous_hash: str) -> str:
        payload = self._payload(record)
        payload["previous_hash"] = previous_hash
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
