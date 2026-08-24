from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Sequence

from .paper import PaperEvent, PaperOrder


class EvidenceKind(StrEnum):
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    CLOSE = "CLOSE"
    REJECTION = "REJECTION"
    FINALIZED = "FINALIZED"


@dataclass(frozen=True)
class EvidenceRecord:
    sequence: int
    timestamp: datetime
    kind: EvidenceKind
    session_id: str
    spec_fingerprint: str
    order_id: int | None
    event: PaperEvent | None
    instrument: int | None
    action: str | None
    quantity: Decimal | None
    price: Decimal | None
    spread: Decimal | None
    slippage: Decimal | None
    latency_ms: float | None
    pnl: Decimal | None
    reason: str
    previous_hash: str
    record_hash: str


class PaperEvidenceJournal:
    """Append-only, hash-chained evidence journal for one paper session."""

    def __init__(self, *, session_id: str, spec_fingerprint: str) -> None:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        if not spec_fingerprint.strip():
            raise ValueError("spec_fingerprint must be non-empty")
        self.session_id = session_id
        self.spec_fingerprint = spec_fingerprint
        self._records: list[EvidenceRecord] = []
        self._finalized = False

    @property
    def records(self) -> Sequence[EvidenceRecord]:
        return tuple(self._records)

    @property
    def head_hash(self) -> str:
        return self._records[-1].record_hash if self._records else "0" * 64

    def append_order(self, order: PaperOrder) -> EvidenceRecord:
        self._require_open()
        kind = {
            PaperEvent.FILLED: EvidenceKind.ORDER,
            PaperEvent.CLOSED: EvidenceKind.CLOSE,
            PaperEvent.REJECTED: EvidenceKind.REJECTION,
        }[order.event]
        return self._append_from_order(order, kind)

    def append_signal(self, order: PaperOrder) -> EvidenceRecord:
        self._require_open()
        return self._append_from_order(order, EvidenceKind.SIGNAL)

    def finalize(self, timestamp: datetime) -> EvidenceRecord:
        self._require_open()
        record = self._append(
            timestamp=timestamp,
            kind=EvidenceKind.FINALIZED,
            order_id=None,
            event=None,
            instrument=None,
            action=None,
            quantity=None,
            price=None,
            spread=None,
            slippage=None,
            latency_ms=None,
            pnl=None,
            reason="Paper evidence journal finalized; no further records permitted.",
        )
        self._finalized = True
        return record

    def verify(self) -> None:
        previous_hash = "0" * 64
        previous_timestamp: datetime | None = None
        for expected_sequence, record in enumerate(self._records, start=1):
            if record.sequence != expected_sequence:
                raise ValueError("evidence sequence is not contiguous")
            if record.session_id != self.session_id:
                raise ValueError("evidence session_id mismatch")
            if record.spec_fingerprint != self.spec_fingerprint:
                raise ValueError("evidence specification fingerprint mismatch")
            if previous_timestamp is not None and record.timestamp < previous_timestamp:
                raise ValueError("evidence timestamps must be chronological")
            if record.previous_hash != previous_hash:
                raise ValueError("evidence hash chain is broken")
            if record.record_hash != self._hash_record(record, previous_hash):
                raise ValueError("evidence record hash mismatch")
            previous_hash = record.record_hash
            previous_timestamp = record.timestamp

        finalized_count = sum(r.kind == EvidenceKind.FINALIZED for r in self._records)
        if finalized_count > 1:
            raise ValueError("evidence journal contains multiple finalization records")
        if self._finalized and finalized_count != 1:
            raise ValueError("finalized evidence journal is missing its finalization record")

    def to_json(self) -> str:
        self.verify()
        return json.dumps(
            {
                "session_id": self.session_id,
                "spec_fingerprint": self.spec_fingerprint,
                "head_hash": self.head_hash,
                "finalized": self._finalized,
                "records": [self._record_payload(r) for r in self._records],
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _append_from_order(self, order: PaperOrder, kind: EvidenceKind) -> EvidenceRecord:
        return self._append(
            timestamp=order.timestamp,
            kind=kind,
            order_id=order.order_id,
            event=order.event,
            instrument=order.instrument,
            action=order.action.value,
            quantity=order.quantity,
            price=order.exit_price if order.event == PaperEvent.CLOSED else order.entry_price,
            spread=order.spread,
            slippage=order.slippage,
            latency_ms=order.latency_ms,
            pnl=order.pnl if order.event == PaperEvent.CLOSED else None,
            reason=order.reason,
        )

    def _append(self, *, timestamp: datetime, kind: EvidenceKind, order_id: int | None,
                event: PaperEvent | None, instrument: int | None, action: str | None,
                quantity: Decimal | None, price: Decimal | None, spread: Decimal | None,
                slippage: Decimal | None, latency_ms: float | None, pnl: Decimal | None,
                reason: str) -> EvidenceRecord:
        if self._records and timestamp < self._records[-1].timestamp:
            raise ValueError("evidence timestamps must be chronological")
        previous_hash = self.head_hash
        record = EvidenceRecord(
            sequence=len(self._records) + 1,
            timestamp=timestamp,
            kind=kind,
            session_id=self.session_id,
            spec_fingerprint=self.spec_fingerprint,
            order_id=order_id,
            event=event,
            instrument=instrument,
            action=action,
            quantity=quantity,
            price=price,
            spread=spread,
            slippage=slippage,
            latency_ms=latency_ms,
            pnl=pnl,
            reason=reason,
            previous_hash=previous_hash,
            record_hash="",
        )
        record = EvidenceRecord(**{**record.__dict__, "record_hash": self._hash_record(record, previous_hash)})
        self._records.append(record)
        return record

    @staticmethod
    def _record_payload(record: EvidenceRecord) -> dict[str, object]:
        return {
            "sequence": record.sequence,
            "timestamp": record.timestamp.isoformat(),
            "kind": record.kind.value,
            "session_id": record.session_id,
            "spec_fingerprint": record.spec_fingerprint,
            "order_id": record.order_id,
            "event": record.event.value if record.event else None,
            "instrument": record.instrument,
            "action": record.action,
            "quantity": str(record.quantity) if record.quantity is not None else None,
            "price": str(record.price) if record.price is not None else None,
            "spread": str(record.spread) if record.spread is not None else None,
            "slippage": str(record.slippage) if record.slippage is not None else None,
            "latency_ms": record.latency_ms,
            "pnl": str(record.pnl) if record.pnl is not None else None,
            "reason": record.reason,
            "previous_hash": record.previous_hash,
        }

    @classmethod
    def _hash_record(cls, record: EvidenceRecord, previous_hash: str) -> str:
        payload = cls._record_payload(record)
        payload["previous_hash"] = previous_hash
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _require_open(self) -> None:
        if self._finalized:
            raise RuntimeError("paper evidence journal is already finalized")
