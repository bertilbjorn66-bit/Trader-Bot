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
    assert FAMILY_SIZE == 324
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


def test_macro_csv_accepts_fred_graph_headers(tmp_path) -> None:
    from datetime import date, timedelta

    from research.cross_asset_macro_discovery import _load_macro_csv

    start = date(2020, 1, 1)
    rows = [
        f"{start + timedelta(days=index)}, {12.3 + (index % 7) / 10:.2f}"
        for index in range(600)
    ]
    path = tmp_path / "VIXCLS.csv"
    path.write_text(
        "observation_date,VIXCLS\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    values = _load_macro_csv(path)
    assert len(values) == 600


def test_asof_panel_uses_latest_observation_before_entry_day() -> None:
    from datetime import date

    from research.cross_asset_macro_discovery import _build_asof_panel

    macro_panel = {
        "VIXCLS": {
            1: {
                date(2020, 1, 1): 1.0,
                date(2020, 1, 3): 3.0,
            }
        }
    }
    entry_days = [date(2020, 1, 2), date(2020, 1, 4)]
    asof = _build_asof_panel(macro_panel, entry_days)
    assert asof["VIXCLS"][1][date(2020, 1, 2)] == 1.0
    assert asof["VIXCLS"][1][date(2020, 1, 4)] == 3.0
