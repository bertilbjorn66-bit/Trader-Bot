from research.cross_asset_macro_discovery import (
    FAMILY_SIZE,
    HORIZONS,
    MACRO_FACTORS,
    MACRO_LOOKBACKS,
    MACRO_STATES,
    MACRO_THRESHOLDS,
    ORIENTATIONS,
    family_hypotheses,
)


def test_family_is_frozen_and_complete() -> None:
    hypotheses = family_hypotheses()
    assert FAMILY_SIZE == 216
    assert len(hypotheses) == FAMILY_SIZE
    assert len({tuple(sorted(item.items())) for item in hypotheses}) == FAMILY_SIZE


def test_axes_are_exact() -> None:
    hypotheses = family_hypotheses()
    assert {item["macro_factor"] for item in hypotheses} == set(MACRO_FACTORS)
    assert {item["macro_lookback"] for item in hypotheses} == set(MACRO_LOOKBACKS)
    assert {item["macro_threshold"] for item in hypotheses} == set(MACRO_THRESHOLDS)
    assert {item["macro_state"] for item in hypotheses} == set(MACRO_STATES)
    assert {item["orientation"] for item in hypotheses} == set(ORIENTATIONS)
    assert {item["horizon"] for item in hypotheses} == set(HORIZONS)
