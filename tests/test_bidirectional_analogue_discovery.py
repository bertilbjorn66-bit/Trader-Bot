from __future__ import annotations

import pytest

from research.bidirectional_analogue_discovery import (
    _robust_discovery_record_set,
    decide_direction,
)


def test_decide_direction_uses_pre_target_mean_advantage() -> None:
    decision = decide_direction([1.0, 2.0, 3.0], [0.5, 0.5, 0.5], 3)
    assert decision is not None
    assert decision[0] == "long"
    assert decision[1] == pytest.approx(2.0)
    assert decision[2] == pytest.approx(1.5)


def test_decide_direction_short_when_short_mean_is_higher() -> None:
    decision = decide_direction([0.4, 0.4, 0.4], [1.0, 2.0, 3.0], 3)
    assert decision is not None
    assert decision[0] == "short"
    assert decision[1] == pytest.approx(2.0)


def test_decide_direction_no_trade_on_tie_or_nonpositive_best_side() -> None:
    assert decide_direction([1.0, 1.0], [1.0, 1.0], 2) is None
    assert decide_direction([-1.0, -1.0], [-2.0, -2.0], 2) is None


def test_discovery_pair_diversification_gate_requires_three_positive_pairs() -> None:
    records = []
    for pair, values in {
        "EUR/USD": [1.0] * 20,
        "GBP/USD": [1.0] * 20,
        "USD/JPY": [1.0] * 20,
    }.items():
        records.extend(
            {
                "pair": pair,
                "outcome_pips": value,
            }
            for value in values
        )
    assert _robust_discovery_record_set(records) is True


def test_discovery_pair_diversification_gate_rejects_one_pair_dominance() -> None:
    records = []
    for pair, values in {
        "EUR/USD": [2.0] * 90,
        "GBP/USD": [1.0] * 20,
        "USD/JPY": [1.0] * 20,
    }.items():
        records.extend(
            {
                "pair": pair,
                "outcome_pips": value,
            }
            for value in values
        )
    assert _robust_discovery_record_set(records) is False
