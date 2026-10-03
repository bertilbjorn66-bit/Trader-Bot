from __future__ import annotations

from research.calendar_seasonality_discovery import (
    FAMILY_SIZE,
    HORIZONS,
    ORIENTATIONS,
    QUARTERS,
    WEEKDAYS,
    family_hypotheses,
)


def test_family_size_is_frozen() -> None:
    hypotheses = family_hypotheses()
    assert FAMILY_SIZE == 120
    assert len(hypotheses) == FAMILY_SIZE
    assert len({tuple(sorted(item.items())) for item in hypotheses}) == FAMILY_SIZE


def test_axes_are_exact() -> None:
    hypotheses = family_hypotheses()
    assert {item["weekday"] for item in hypotheses} == set(WEEKDAYS)
    assert {item["quarter"] for item in hypotheses} == set(QUARTERS)
    assert {item["orientation"] for item in hypotheses} == set(ORIENTATIONS)
    assert {item["horizon"] for item in hypotheses} == set(HORIZONS)


def test_no_live_flags_are_default_false() -> None:
    from research import calendar_seasonality_discovery as module
    assert module.family_hypotheses()
