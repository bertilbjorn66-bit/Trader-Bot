from __future__ import annotations

from research.enriched_conditional_experiment import evaluate, wilson_interval


def test_wilson_interval_is_bounded() -> None:
    low, high = wilson_interval(0.5, 200)
    assert low is not None and high is not None
    assert 0.0 < low < 0.5 < high < 1.0


def test_evaluate_applies_distance_and_agreement_filters() -> None:
    records = [
        {"split": "discovery", "median_distance": 0.4, "agreement": 0.8, "outcome_pips": 2.0},
        {"split": "discovery", "median_distance": 0.7, "agreement": 0.8, "outcome_pips": 1.0},
        {"split": "discovery", "median_distance": 0.4, "agreement": 0.4, "outcome_pips": -5.0},
        {"split": "confirmation", "median_distance": 0.4, "agreement": 0.8, "outcome_pips": -1.0},
    ]
    result = evaluate(records, distance_max=0.5, agreement_min=0.7, split="discovery")
    assert result is not None
    assert result["n"] == 1
    assert result["expectancy_pips"] == 2.0
    assert result["win_rate"] == 1.0


def test_confirmation_is_separate_from_discovery() -> None:
    records = [
        {"split": "discovery", "median_distance": 0.2, "agreement": 0.8, "outcome_pips": 3.0},
        {"split": "confirmation", "median_distance": 0.2, "agreement": 0.8, "outcome_pips": -2.0},
    ]
    discovery = evaluate(records, agreement_min=0.7, split="discovery")
    confirmation = evaluate(records, agreement_min=0.7, split="confirmation")
    assert discovery is not None and confirmation is not None
    assert discovery["expectancy_pips"] == 3.0
    assert confirmation["expectancy_pips"] == -2.0
