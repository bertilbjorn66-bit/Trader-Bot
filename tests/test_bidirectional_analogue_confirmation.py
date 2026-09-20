from __future__ import annotations

import pytest

from research.bidirectional_analogue_confirmation import (
    candidate_fingerprint,
    candidate_identity,
    evaluate_confirmation,
)


def _candidate() -> dict[str, object]:
    return {
        "direction": "bidirectional",
        "direction_policy": "pre_target_analogue_mean_argmax",
        "horizon": 3,
        "k": 25,
    }


def _record(pair: str, direction: str, value: float, timestamp: str) -> dict[str, object]:
    return {
        "pair": pair,
        "direction": direction,
        "horizon": 3,
        "k": 25,
        "global_split": "confirmation",
        "timestamp": timestamp,
        "outcome_pips": value,
    }


def test_candidate_identity_rejects_fixed_direction_substitution() -> None:
    candidate = _candidate()
    identity = candidate_identity(candidate)
    assert identity["direction"] == "bidirectional"
    assert identity["direction_policy"] == "pre_target_analogue_mean_argmax"
    assert candidate_fingerprint(candidate) != candidate_fingerprint({**candidate, "direction": "long"})


def test_confirmation_requires_bidirectional_identity() -> None:
    report = {
        "status": "BIDIRECTIONAL_ANALOGUE_DISCOVERY_COMPLETED",
        "selection_policy": {
            "contract_version": "v1-bidirectional-analogue-familywise",
            "confirmation_used_for_selection": False,
            "prior_frozen_confirmation_artifact_read": False,
        },
        "top_candidates": [
            {
                "direction": "long",
                "direction_policy": "pre_target_analogue_mean_argmax",
                "horizon": 3,
                "k": 25,
                "candidate_fingerprint": candidate_fingerprint(
                    {
                        "direction": "long",
                        "direction_policy": "pre_target_analogue_mean_argmax",
                        "horizon": 3,
                        "k": 25,
                    }
                ),
            }
        ],
    }
    with pytest.raises(ValueError, match="bidirectional"):
        evaluate_confirmation(report, [])


def test_confirmation_without_candidate_does_not_authorize_anything() -> None:
    report = {
        "status": "BIDIRECTIONAL_ANALOGUE_DISCOVERY_COMPLETED",
        "selection_policy": {
            "contract_version": "v1-bidirectional-analogue-familywise",
            "confirmation_used_for_selection": False,
            "prior_frozen_confirmation_artifact_read": False,
        },
        "top_candidates": [],
    }
    result = evaluate_confirmation(report, [])
    assert result["state"] == "INCOMPLETE"
    assert result["promotion_authorized"] is False
    assert result["live_execution_authorized"] is False
