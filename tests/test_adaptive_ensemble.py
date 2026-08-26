from __future__ import annotations

from research.adaptive_ensemble_v2 import Stat, conservative_edge, sign, votes_for_state


def test_stat_edge_is_conservative() -> None:
    stat = Stat()
    for value in [2.0, 1.8, 2.2, 2.1, 1.9] * 20:
        stat.add(value)
    assert conservative_edge(stat) < stat.mean
    assert conservative_edge(stat) > 0


def test_sign_and_strategy_set_are_multi_hypothesis() -> None:
    assert sign(2.0) == 1
    assert sign(-2.0) == -1
    assert sign(0.0) == 0
