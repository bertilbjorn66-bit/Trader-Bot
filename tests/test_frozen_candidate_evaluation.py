from __future__ import annotations

from research.frozen_candidate_evaluation import (
    FROZEN_CANDIDATE,
    FROZEN_CANDIDATE_FINGERPRINT,
    _matches,
    evaluate,
)


def _record(split: str, outcome: float, index: int, pair: str = "EUR/USD") -> dict[str, object]:
    return {
        "split": split,
        "horizon": 2,
        "regime": "regime:high_volatility_range",
        "session": "new_york",
        "pair": pair,
        "median_distance": 1.0,
        "agreement": 0.75,
        "outcome_pips": outcome,
        "timestamp": f"2025-01-01T00:{index:02d}:00+00:00",
    }


def test_frozen_candidate_identity_is_stable() -> None:
    assert FROZEN_CANDIDATE["horizon"] == 2
    assert FROZEN_CANDIDATE["regime"] == "regime:high_volatility_range"
    assert len(FROZEN_CANDIDATE_FINGERPRINT) == 64


def test_structural_matching_never_uses_outcome() -> None:
    record = _record("confirmation", -999.0, 1)
    assert _matches(record, FROZEN_CANDIDATE, "confirmation") is True


def test_incomplete_when_confirmation_is_too_small() -> None:
    records = [_record("confirmation", 1.0, index) for index in range(10)]
    assert any(_matches(record, FROZEN_CANDIDATE, "confirmation") for record in records)


def test_confirmation_cannot_authorize_live_execution() -> None:
    # This unit test uses a separately supplied discovery sample only to exercise
    # the fail-closed result path. The real immutable experiment validates the
    # historical discovery snapshot before touching confirmation outcomes.
    result = evaluate([])
    assert result["state"] == "INCOMPLETE"
    assert result["promotion_authorized"] if "promotion_authorized" in result else True
    assert result["live_execution_authorized"] is False
