from datetime import timedelta

import pytest

from research.execution import ExecutionAssumptions
from research.sequential_empirical import _calibration
from research.synthetic import generate_bars
from trader_bot.models import MarketBar, OfferSide, Timeframe
from trader_bot.validation import expanding_walk_forward


def test_calibration_is_bounded_and_shape_safe() -> None:
    result = _calibration([0.25, 0.75, 1.0], [False, True, True])
    assert result["n"] == 3
    assert 0.0 <= float(result["brier"]) <= 1.0
    assert 0.0 <= float(result["predicted_rate"]) <= 1.0
    assert 0.0 <= float(result["realized_rate"]) <= 1.0


def test_walk_forward_purge_stays_before_test_window() -> None:
    timestamps = [generate_bars(250)[i].timestamp for i in range(250)]
    folds = expanding_walk_forward(
        timestamps,
        timedelta(days=2),
        timedelta(days=1),
        step=timedelta(days=1),
        purge=timedelta(hours=2),
    )
    assert folds
    assert all(f.train_end < f.test_start < f.test_end for f in folds)


def test_execution_assumptions_reject_negative_costs() -> None:
    with pytest.raises(ValueError):
        ExecutionAssumptions(slippage=-0.1)


def test_synthetic_generator_provides_timezone_aware_market_bars() -> None:
    bars = generate_bars(120)
    assert bars
    assert all(bar.timestamp.tzinfo is not None for bar in bars)
