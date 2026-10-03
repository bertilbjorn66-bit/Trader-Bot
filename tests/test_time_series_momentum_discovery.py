from __future__ import annotations

from research.time_series_momentum_discovery import (
    FAMILY_SIZE,
    HORIZONS,
    LOOKBACKS,
    ORIENTATIONS,
    THRESHOLDS,
    family_hypotheses,
)


def test_family_is_frozen_and_unique() -> None:
    hypotheses = family_hypotheses()
    assert FAMILY_SIZE == 120
    assert len(hypotheses) == FAMILY_SIZE
    assert len({tuple(sorted(h.items())) for h in hypotheses}) == FAMILY_SIZE


def test_family_axes_are_exact() -> None:
    hypotheses = family_hypotheses()
    assert {h["lookback"] for h in hypotheses} == set(LOOKBACKS)
    assert {h["threshold"] for h in hypotheses} == set(THRESHOLDS)
    assert {h["orientation"] for h in hypotheses} == set(ORIENTATIONS)
    assert {h["horizon"] for h in hypotheses} == set(HORIZONS)


def test_no_lookahead_contract_is_encoded() -> None:
    import inspect

    from research import time_series_momentum_discovery as module

    source = inspect.getsource(module._outcomes)
    assert "signal_index = index - 1" in source
    assert "entry = bars[index]" in source
    assert "target = bars[index + horizon - 1]" in source
