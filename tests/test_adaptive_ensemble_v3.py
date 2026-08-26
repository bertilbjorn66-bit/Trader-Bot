from __future__ import annotations

from datetime import datetime, timezone

from research.adaptive_ensemble_v3 import Stat, conservative_edge, route, strategy_votes
from research.pipeline import state_from_bar_window
from research.types import Bar


def test_conservative_edge_penalizes_uncertainty() -> None:
    strong = Stat()
    weak = Stat()
    for value in [2.0, 1.8, 2.2, 2.1, 1.9] * 20:
        strong.add(value)
    for value in [8.0, -7.0, 6.0, -5.0, 4.0] * 20:
        weak.add(value)
    assert conservative_edge(strong) > 0
    assert conservative_edge(strong) > conservative_edge(weak)


def test_strategy_votes_are_multi_expert() -> None:
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
    votes = strategy_votes(state, history)
    assert len(votes) == 8
    assert any(direction != 0 for direction, _ in votes.values())


def test_route_abstains_without_positive_edge() -> None:
    votes = {"trend": (1, 0.9), "momentum": (1, 0.8)}
    lead, direction, confidence, reason = route(votes, {}, {}, 1, "EUR/USD", "regime:trend_up", "london")
    assert lead is None
    assert direction == 0
    assert confidence == 0.0
    assert "edge" in reason


def test_route_requires_multi_expert_consensus() -> None:
    trend = Stat()
    momentum = Stat()
    for value in [1.2, 1.0, 1.1, 0.9] * 20:
        trend.add(value)
    for value in [0.9, 0.8, 0.7, 0.6] * 20:
        momentum.add(value)
    local = {
        (("EUR/USD", "regime:trend_up", "london"), "trend", 1): trend,
        (("EUR/USD", "regime:trend_up", "london"), "momentum", 1): momentum,
    }
    votes = {"trend": (1, 0.8), "momentum": (1, 0.8), "reversal": (-1, 0.9)}
    lead, direction, confidence, reason = route(
        votes, local, {("trend", 1): trend, ("momentum", 1): momentum}, 1,
        "EUR/USD", "regime:trend_up", "london"
    )
    assert lead in {"trend", "momentum"}
    assert direction == 1
    assert confidence > 0.70
    assert reason == "multi_expert_consensus"
