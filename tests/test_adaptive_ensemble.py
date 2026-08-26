from __future__ import annotations

from datetime import datetime, timezone

from research.adaptive_ensemble import Stat, _lower_bound, _select_strategy, _strategy_votes
from research.pipeline import state_from_bar_window
from research.types import Bar


def test_stat_lower_bound_is_conservative() -> None:
    stat = Stat()
    for value in [2.0, 1.8, 2.2, 2.1, 1.9] * 20:
        stat.update(value)
    assert _lower_bound(stat) < stat.mean
    assert _lower_bound(stat) > 0


def test_strategy_votes_cover_multiple_hypotheses() -> None:
    bars = []
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for index in range(30):
        price = 1.10 + index * 0.001
        bars.append(
            Bar(
                timestamp=start.replace(minute=index),
                bid_open=price,
                bid_high=price + 0.0005,
                bid_low=price - 0.0002,
                bid_close=price + 0.0003,
                ask_open=price + 0.0001,
                ask_high=price + 0.0006,
                ask_low=price - 0.0001,
                ask_close=price + 0.0004,
            )
        )
    state = state_from_bar_window(bars, 25, 20)
    history = [state_from_bar_window(bars, i, 20) for i in range(20, 25)]
    votes = _strategy_votes(state, history)
    assert len(votes) >= 7
    assert {name for name, (direction, _) in votes.items() if direction != 0}


def test_router_abstains_without_historical_edge() -> None:
    votes = {"trend_follow": (1, 0.8)}
    strategy, direction, confidence, reason = _select_strategy(
        votes, {}, {}, 1, "EUR/USD", "regime:trend_up", "london"
    )
    assert strategy is None
    assert direction == 0
    assert confidence == 0.0
    assert "positive" in reason


def test_router_selects_only_supported_historical_winner() -> None:
    votes = {"trend_follow": (1, 0.8), "momentum": (-1, 0.8)}
    stats = {}
    trend_stat = Stat()
    momentum_stat = Stat()
    for value in [1.2, 1.0, 1.1, 0.9] * 10:
        trend_stat.update(value)
    for value in [-0.8, -0.6, -0.7, -0.9] * 10:
        momentum_stat.update(value)
    stats[(('EUR/USD', 'regime:trend_up', 'london'), 'trend_follow', 1)] = trend_stat
    stats[(('EUR/USD', 'regime:trend_up', 'london'), 'momentum', 1)] = momentum_stat
    strategy, direction, confidence, _reason = _select_strategy(
        votes, stats, {('trend_follow', 1): trend_stat, ('momentum', 1): momentum_stat}, 1,
        'EUR/USD', 'regime:trend_up', 'london'
    )
    assert strategy == 'trend_follow'
    assert direction == 1
    assert confidence > 0.5
