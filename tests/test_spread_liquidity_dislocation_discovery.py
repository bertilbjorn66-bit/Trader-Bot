from research.spread_liquidity_dislocation_discovery import (
    FAMILY_SIZE,
    HORIZONS,
    ORIENTATIONS,
    SPREAD_STATES,
    SPREAD_THRESHOLDS,
    SPREAD_WINDOWS,
    family_hypotheses,
)


def test_family_is_frozen_and_complete() -> None:
    hypotheses = family_hypotheses()
    assert FAMILY_SIZE == 144
    assert len(hypotheses) == FAMILY_SIZE
    assert len({tuple(sorted(item.items())) for item in hypotheses}) == FAMILY_SIZE


def test_axes_are_exact() -> None:
    hypotheses = family_hypotheses()
    assert {item["spread_window"] for item in hypotheses} == set(SPREAD_WINDOWS)
    assert {item["spread_threshold"] for item in hypotheses} == set(SPREAD_THRESHOLDS)
    assert {item["spread_state"] for item in hypotheses} == set(SPREAD_STATES)
    assert {item["orientation"] for item in hypotheses} == set(ORIENTATIONS)
    assert {item["horizon"] for item in hypotheses} == set(HORIZONS)
