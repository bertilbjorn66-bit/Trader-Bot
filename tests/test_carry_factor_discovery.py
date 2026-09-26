from __future__ import annotations

from datetime import date

from research.carry_factor_discovery import (
    CARRY_THRESHOLDS,
    HORIZONS,
    TREND_STRENGTH_MIN,
    VOLATILITY_STATES,
    _grid,
    _parse_sdmx_series,
    _strict_prior_rate,
)


def test_family_size_is_predeclared() -> None:
    assert len(_grid()) == 144


def test_strict_prior_rate_prevents_same_day_lookahead() -> None:
    series = [(date(2026, 1, 2), 2.0), (date(2026, 1, 5), 2.5)]
    assert _strict_prior_rate(series, date(2026, 1, 2)) is None
    assert _strict_prior_rate(series, date(2026, 1, 3)) == 2.0
    assert _strict_prior_rate(series, date(2026, 1, 5)) == 2.0
    assert _strict_prior_rate(series, date(2026, 1, 6)) == 2.5


def test_sdmx_xml_parser_extracts_one_series() -> None:
    payload = b"""
    <message:StructureSpecificData xmlns:message="urn:sdmx:org.sdmx.infomodel.datastructure:StructureSpecificData:2.1">
      <message:DataSet>
        <Series FREQ="D" REF_AREA="US">
          <Obs TIME_PERIOD="2026-01-02" OBS_VALUE="4.33"/>
          <Obs TIME_PERIOD="2026-01-05" OBS_VALUE="4.33"/>
        </Series>
      </message:DataSet>
    </message:StructureSpecificData>
    """
    assert _parse_sdmx_series(payload) == [
        (date(2026, 1, 2), 4.33),
        (date(2026, 1, 5), 4.33),
    ]


def test_grid_values_are_fixed() -> None:
    assert CARRY_THRESHOLDS == (0.25, 0.50, 1.00, 2.00)
    assert TREND_STRENGTH_MIN == (0.00, 0.25, 0.50)
    assert HORIZONS == (6, 36, 144)
    assert VOLATILITY_STATES == ("any", "high", "normal", "low")
