from __future__ import annotations

from research.fresh_candidate_confirmation import (
    MAX_PAIR_OBSERVATION_SHARE,
    _matches,
    candidate_fingerprint,
    evaluate_primary,
)


def _candidate() -> dict[str, object]:
    return {
        "horizon": 2,
        "agreement_min": 0.5,
        "distance_max": 1.5,
        "regime": "regime:high_volatility_range",
        "session": "new_york",
        "pairset": "all",
        "discovery": {"n": 200, "expectancy_pips": 1.0, "profit_factor": 1.4},
    }


def _record(split: str, pair: str, outcome: float, minute: int, agreement: float = 0.7) -> dict[str, object]:
    return {
        "split": split,
        "pair": pair,
        "horizon": 2,
        "regime": "regime:high_volatility_range",
        "session": "new_york",
        "median_distance": 1.0,
        "agreement": agreement,
        "outcome_pips": outcome,
        "timestamp": f"2025-01-01T00:{minute:02d}:00+00:00",
    }


def _report() -> dict[str, object]:
    return {
        "status": "FRESH_DISCOVERY_COMPLETED",
        "selection_policy": {
            "confirmation_used_for_selection": False,
            "prior_frozen_confirmation_artifact_read": False,
        },
        "candidate_count": 1,
        "record_count": 400,
        "top_candidates": [_candidate()],
    }


def test_matcher_uses_candidate_thresholds() -> None:
    candidate = _candidate()
    assert _matches(_record("confirmation", "EUR/USD", 1.0, 1), candidate, "confirmation") is True
    record = _record("confirmation", "EUR/USD", 1.0, 1, agreement=0.4)
    assert _matches(record, candidate, "confirmation") is False


def test_candidate_fingerprint_is_stable() -> None:
    assert len(candidate_fingerprint(_candidate())) == 64


def test_no_candidate_is_fail_closed() -> None:
    report = {"status": "FRESH_DISCOVERY_COMPLETED", "selection_policy": {"confirmation_used_for_selection": False, "prior_frozen_confirmation_artifact_read": False}, "top_candidates": []}
    result = evaluate_primary(report, [])
    assert result["state"] == "INCOMPLETE"
    assert result["promotion_authorized"] is False
    assert result["live_execution_authorized"] is False


def test_pair_concentration_limit_is_explicit() -> None:
    assert 0 < MAX_PAIR_OBSERVATION_SHARE < 1
