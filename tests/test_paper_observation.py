from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trader_bot.decision import Action, Decision
from trader_bot.models import Instrument, Quote
from trader_bot.paper_eval import PaperEvaluationSpec
from trader_bot.paper_observation import (
    ObservationGuard,
    ObservationStatus,
    PaperObservationJournal,
    PaperObservationRunner,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


class FakeProvider:
    def __init__(self, quote: Quote, healthy: bool = True) -> None:
        self.quote = quote
        self.healthy = healthy
        self.historical_called = False

    def instruments(self):
        return (Instrument(id=self.quote.instrument, name="EUR/USD"),)

    def historical_bars(self, request):
        self.historical_called = True
        raise AssertionError("paper observation runner must not request historical data")

    def current_quotes(self, instruments):
        assert instruments == [self.quote.instrument]
        return (self.quote,)

    def health_check(self):
        return self.healthy


def quote(ts: datetime = NOW, bid: str = "1.1000", ask: str = "1.1002") -> Quote:
    return Quote(
        timestamp=ts,
        instrument=1,
        bid=Decimal(bid),
        ask=Decimal(ask),
    )


def spec() -> PaperEvaluationSpec:
    return PaperEvaluationSpec(
        "candidate-a", "1", "frozen-reference-1", Decimal("-1"), 1
    )


def decision(_quote: Quote) -> Decision:
    return Decision(Action.BUY, 0.8, "validated evidence", 250)


def runner(provider: FakeProvider) -> PaperObservationRunner:
    return PaperObservationRunner(
        provider=provider,
        instrument=1,
        session_id="paper-observation-1",
        spec=spec(),
        guard=ObservationGuard(
            max_quote_age=timedelta(seconds=5),
            max_spread=Decimal("0.0005"),
        ),
        decision_factory=decision,
        quantity=Decimal("1"),
        stop_distance=Decimal("0.0010"),
        target_distance=Decimal("0.0020"),
    )


def test_accepted_live_quote_creates_paper_order_without_historical_access() -> None:
    provider = FakeProvider(quote())
    paper = runner(provider)
    result = paper.poll(observed_at=NOW + timedelta(seconds=1))
    assert result.observation is not None
    assert result.observation.status == ObservationStatus.ACCEPTED
    assert result.order is not None
    assert provider.historical_called is False
    assert paper.observations.head_hash != "0" * 64
    paper.observations.verify()


def test_stale_quote_is_rejected_without_creating_order() -> None:
    provider = FakeProvider(quote(NOW - timedelta(seconds=6)))
    paper = runner(provider)
    result = paper.poll(observed_at=NOW)
    assert result.observation is not None
    assert result.observation.status == ObservationStatus.REJECTED
    assert result.order is None


def test_wide_spread_is_rejected_without_creating_order() -> None:
    provider = FakeProvider(quote(ask="1.1010"))
    paper = runner(provider)
    result = paper.poll(observed_at=NOW)
    assert result.observation is not None
    assert result.observation.status == ObservationStatus.REJECTED
    assert result.order is None


def test_future_quote_beyond_allowed_skew_is_rejected() -> None:
    provider = FakeProvider(quote(NOW + timedelta(seconds=4)))
    paper = runner(provider)
    result = paper.poll(observed_at=NOW)
    assert result.observation is not None
    assert result.observation.status == ObservationStatus.REJECTED


def test_unhealthy_provider_does_not_fabricate_observation() -> None:
    provider = FakeProvider(quote(), healthy=False)
    paper = runner(provider)
    result = paper.poll(observed_at=NOW)
    assert result.observation is None
    assert result.order is None
    assert paper.observations.records == ()


def test_observation_tampering_breaks_hash_verification() -> None:
    journal = PaperObservationJournal(
        session_id="paper-observation-1",
        spec_fingerprint=spec().fingerprint(),
    )
    record = journal.append(
        quote=quote(),
        status=ObservationStatus.ACCEPTED,
        reason="ok",
    )
    journal._records[0] = record.__class__(**{**record.__dict__, "bid": Decimal("9")})
    with pytest.raises(ValueError, match="record hash mismatch"):
        journal.verify()
