from __future__ import annotations

from datetime import datetime, timezone

from research.adaptive_ensemble_v5 import (
    CANDIDATE_FINGERPRINT,
    CANDIDATE_SPEC,
    CONFIRMATION_FRACTION,
    DISCOVERY_FRACTION,
    Stat,
    conservative_edge,
    route,
    strategy_votes,
)
from research.pipeline import state_from_bar_window
from research.types import Bar


def test_conservative_edge_penalizes_noise() -> None:
    stable = Stat()
    noisy = Stat()
    for value in [2.0, 1.8, 2.2, 2.1, 1.9] * 20:
        stable.add(value)
    for value in [8.0, -7.0, 6.0, -5.0, 4.0] * 20:
        noisy.add(value)
    assert conservative_edge(stable) > 0.0
    assert conservative_edge(stable) > conservative_edge(noisy)


def test_strategy_votes_expose_eight_experts() -> None:
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


def test_route_abstains_without_evidence() -> None:
    lead, direction, confidence, reason = route(
        {"trend": (1, 0.9), "momentum": (1, 0.8)}, {}, {}, 1,
        "EUR/USD", "regime:trend_up", "london"
    )
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
    lead, direction, confidence, reason = route(
        {"trend": (1, 0.8), "momentum": (1, 0.8), "reversal": (-1, 0.9)},
        local,
        {("trend", 1): trend, ("momentum", 1): momentum},
        1,
        "EUR/USD",
        "regime:trend_up",
        "london",
    )
    assert lead in {"trend", "momentum"}
    assert direction == 1
    assert confidence > 0.70
    assert reason == "multi_expert_consensus"


def test_candidate_contract_is_immutable_and_frozen_for_holdout() -> None:
    assert DISCOVERY_FRACTION == 0.60
    assert CONFIRMATION_FRACTION == 0.40
    assert CANDIDATE_SPEC["discovery_fraction"] == DISCOVERY_FRACTION
    assert CANDIDATE_SPEC["confirmation_fraction"] == CONFIRMATION_FRACTION
    assert len(CANDIDATE_FINGERPRINT) == 64
    assert CANDIDATE_SPEC["strategy_set"] == (
        "trend",
        "momentum",
        "breakout",
        "mean_reversion",
        "pullback",
        "volatility",
        "reversal",
        "analogue",
    )
