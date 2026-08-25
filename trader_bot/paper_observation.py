from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Callable, Sequence

from .data_provider import MarketDataProvider
from .decision import Action, Decision
from .models import Quote
from .paper import PaperOrder
from .paper_eval import PaperEvaluationResult, PaperEvaluationSpec
from .paper_evidence_session import EvidenceBackedPaperSession


class ObservationStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class PaperObservation:
    sequence: int
    timestamp: datetime
    instrument: int
    bid: Decimal
    ask: Decimal
    spread: Decimal
    status: ObservationStatus
    reason: str
    previous_hash: str
    record_hash: str


class PaperObservationJournal:
    """Append-only tamper-evident journal for real market observations."""

    def __init__(self, *, session_id: str, spec_fingerprint: str) -> None:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        if not spec_fingerprint.strip():
            raise ValueError("spec_fingerprint must be non-empty")
        self.session_id = session_id
        self.spec_fingerprint = spec_fingerprint
        self._records: list[PaperObservation] = []

    @property
    def records(self) -> Sequence[PaperObservation]:
        return tuple(self._records)

    @property
    def head_hash(self) -> str:
        return self._records[-1].record_hash if self._records else "0" * 64

    def append(
        self,
        *,
        quote: Quote,
        status: ObservationStatus,
        reason: str,
    ) -> PaperObservation:
        if self._records and quote.timestamp < self._records[-1].timestamp:
            raise ValueError("observation timestamps must be chronological")
        previous_hash = self.head_hash
        record = PaperObservation(
            sequence=len(self._records) + 1,
            timestamp=quote.timestamp,
            instrument=quote.instrument,
            bid=quote.bid,
            ask=quote.ask,
            spread=quote.ask - quote.bid,
            status=status,
            reason=reason,
            previous_hash=previous_hash,
            record_hash="",
        )
        record = PaperObservation(
            **{**record.__dict__, "record_hash": self._hash_record(record, previous_hash)}
        )
        self._records.append(record)
        return record

    def verify(self) -> None:
        previous_hash = "0" * 64
        previous_timestamp: datetime | None = None
        for expected_sequence, record in enumerate(self._records, start=1):
            if record.sequence != expected_sequence:
                raise ValueError("observation sequence is not contiguous")
            if previous_timestamp is not None and record.timestamp < previous_timestamp:
                raise ValueError("observation timestamps must be chronological")
            if record.previous_hash != previous_hash:
                raise ValueError("observation hash chain is broken")
            if record.record_hash != self._hash_record(record, previous_hash):
                raise ValueError("observation record hash mismatch")
            previous_hash = record.record_hash
            previous_timestamp = record.timestamp

    def to_json(self) -> str:
        self.verify()
        return json.dumps(
            {
                "session_id": self.session_id,
                "spec_fingerprint": self.spec_fingerprint,
                "head_hash": self.head_hash,
                "records": [self._payload(record) for record in self._records],
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _payload(record: PaperObservation) -> dict[str, object]:
        return {
            "sequence": record.sequence,
            "timestamp": record.timestamp.isoformat(),
            "instrument": record.instrument,
            "bid": str(record.bid),
            "ask": str(record.ask),
            "spread": str(record.spread),
            "status": record.status.value,
            "reason": record.reason,
            "previous_hash": record.previous_hash,
        }

    @classmethod
    def _hash_record(cls, record: PaperObservation, previous_hash: str) -> str:
        payload = cls._payload(record)
        payload["previous_hash"] = previous_hash
        payload["session_id"] = record.sequence
        payload["spec_fingerprint"] = "bound"
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class ObservationGuard:
    max_quote_age: timedelta
    max_spread: Decimal
    max_future_skew: timedelta = timedelta(seconds=2)

    def __post_init__(self) -> None:
        if self.max_quote_age <= timedelta(0):
            raise ValueError("max_quote_age must be positive")
        if self.max_spread < Decimal("0"):
            raise ValueError("max_spread must be non-negative")
        if self.max_future_skew < timedelta(0):
            raise ValueError("max_future_skew must be non-negative")


@dataclass(frozen=True)
class PaperObservationResult:
    observation: PaperObservation
    order: PaperOrder | None
    reason: str


DecisionFactory = Callable[[Quote], Decision]


class PaperObservationRunner:
    """Consumes current quotes only and routes decisions into non-transmitting paper execution."""

    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        instrument: int,
        session_id: str,
        spec: PaperEvaluationSpec,
        guard: ObservationGuard,
        decision_factory: DecisionFactory,
        quantity: Decimal,
        stop_distance: Decimal,
        target_distance: Decimal,
    ) -> None:
        if instrument <= 0:
            raise ValueError("instrument must be positive")
        if quantity <= Decimal("0"):
            raise ValueError("quantity must be positive")
        self.provider = provider
        self.instrument = instrument
        self.guard = guard
        self.decision_factory = decision_factory
        self.quantity = quantity
        self.stop_distance = stop_distance
        self.target_distance = target_distance
        self.session = EvidenceBackedPaperSession(
            session_id=session_id,
            spec=spec,
            started_at=datetime.now(timezone.utc),
        )
        self.observations = PaperObservationJournal(
            session_id=session_id,
            spec_fingerprint=spec.fingerprint(),
        )

    def poll(self, *, observed_at: datetime | None = None) -> PaperObservationResult:
        now = observed_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.provider.health_check():
            quote = self._quote_or_fail(now)
            observation = self.observations.append(
                quote=quote,
                status=ObservationStatus.REJECTED,
                reason="Market-data provider health check failed.",
            )
            return PaperObservationResult(observation, None, observation.reason)

        quote = self._quote_or_fail(now)
        age = now - quote.timestamp
        spread = quote.ask - quote.bid
        if age > self.guard.max_quote_age:
            observation = self.observations.append(
                quote=quote,
                status=ObservationStatus.REJECTED,
                reason=f"Quote is stale by {age.total_seconds():.3f}s.",
            )
            return PaperObservationResult(observation, None, observation.reason)
        if age < -self.guard.max_future_skew:
            observation = self.observations.append(
                quote=quote,
                status=ObservationStatus.REJECTED,
                reason="Quote timestamp is too far in the future.",
            )
            return PaperObservationResult(observation, None, observation.reason)
        if spread > self.guard.max_spread:
            observation = self.observations.append(
                quote=quote,
                status=ObservationStatus.REJECTED,
                reason=f"Spread {spread} exceeds guard {self.guard.max_spread}.",
            )
            return PaperObservationResult(observation, None, observation.reason)

        observation = self.observations.append(
            quote=quote,
            status=ObservationStatus.ACCEPTED,
            reason="Quote passed health, freshness, future-skew, and spread guards.",
        )
        decision = self.decision_factory(quote)
        if decision.action not in (Action.BUY, Action.SELL):
            return PaperObservationResult(observation, None, "Decision did not authorize a paper entry.")
        order = self.session.record_signal(
            decision=decision,
            quote=quote,
            quantity=self.quantity,
            stop_distance=self.stop_distance,
            target_distance=self.target_distance,
        )
        self.session.evidence.verify()
        return PaperObservationResult(observation, order, "Paper order recorded; no broker transmission occurred.")

    def finalize(self, finalized_at: datetime | None = None) -> PaperEvaluationResult:
        timestamp = finalized_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            raise ValueError("finalized_at must be timezone-aware")
        self.observations.verify()
        result = self.session.finalize(timestamp)
        self.observations.verify()
        return result

    def _quote_or_fail(self, now: datetime) -> Quote:
        quotes = self.provider.current_quotes([self.instrument])
        if len(quotes) != 1:
            raise ValueError("provider must return exactly one quote for the requested instrument")
        quote = quotes[0]
        if quote.instrument != self.instrument:
            raise ValueError("provider returned a quote for the wrong instrument")
        if quote.timestamp.tzinfo is None:
            raise ValueError("provider returned a timezone-naive quote timestamp")
        if quote.timestamp > now + self.guard.max_future_skew:
            return quote
        return quote
