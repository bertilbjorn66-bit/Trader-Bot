from datetime import timedelta

import pytest

from research.outcomes import future_outcome
from research.similarity import fit_scaler, nearest_states
from research.statistics import expectancy, probability_summary
from research.synthetic import generate_bars
from research.validation import expanding_walk_forward
from research.pipeline import build_states, research_snapshot


def test_synthetic_data_and_states_are_deterministic() -> None:
    bars = generate_bars(120)
    states = build_states(bars)
    assert len(bars) == 120
    assert len(states) == 100
    assert bars[1].timestamp > bars[0].timestamp
    assert states[-1].timestamp == bars[-1].timestamp


def test_outcome_uses_direction_correct_bid_ask() -> None:
    bars = generate_bars(100)
    long_outcome = future_outcome(bars, 50, 5, "long")
    short_outcome = future_outcome(bars, 50, 5, "short")
    assert long_outcome.entry == bars[50].ask_close
    assert short_outcome.entry == bars[50].bid_close
    assert long_outcome.mfe_abs >= 0
    assert long_outcome.mae_abs >= 0


def test_similarity_excludes_future_states() -> None:
    states = build_states(generate_bars(120))
    target = states[-1]
    history = states[:-1]
    scaler = fit_scaler(history)
    neighbors = nearest_states(target, history, scaler, k=10)
    assert neighbors
    assert all(s.timestamp < target.timestamp for s, _ in neighbors)


def test_statistics_and_walk_forward() -> None:
    stats = probability_summary([1.0, -1.0, 2.0, -0.5])
    ev = expectancy([1.0, -1.0, 2.0, -0.5], transaction_cost=0.1)
    assert stats["n"] == 4
    assert 0 <= float(stats["probability"]) <= 1
    assert ev["expectancy"] is not None
    timestamps = [generate_bars(30)[i].timestamp for i in range(30)]
    folds = expanding_walk_forward(timestamps, timedelta(days=1), timedelta(hours=6))
    assert folds
    assert all(f.train_end <= f.test_start for f in folds)


def test_end_to_end_snapshot_is_explicitly_non_empirical() -> None:
    bars = generate_bars(220)
    snapshot = research_snapshot(bars, target_index=180, horizon=5, k=20)
    assert snapshot["empirical"] is False
    assert "SYNTHETIC" in str(snapshot["warning"])


def test_invalid_input_rejected() -> None:
    with pytest.raises(ValueError):
        generate_bars(10)
