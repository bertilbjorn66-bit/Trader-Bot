from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

from research.cftc_positioning_discovery import (
    FAMILY_SIZE,
    _find_header,
    _market_currency,
    _next_monday,
    _rolling_z,
    family_hypotheses,
)


def test_family_size_is_frozen() -> None:
    assert FAMILY_SIZE == 144
    assert len(family_hypotheses()) == 144


def test_market_mapping_is_explicit_for_all_currencies() -> None:
    samples = {
        "EURO FX - CHICAGO MERCANTILE EXCHANGE": "EUR",
        "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE": "GBP",
        "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE": "JPY",
        "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": "AUD",
        "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE": "CAD",
        "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE": "CHF",
        "NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE": "NZD",
        "U.S. DOLLAR INDEX - ICE FUTURES U.S.": "USD",
    }
    assert {key: _market_currency(key) for key in samples} == samples


def test_next_monday_is_strictly_after_tuesday_report() -> None:
    assert _next_monday(date(2026, 9, 29)) == date(2026, 10, 5)


def test_rolling_z_excludes_current_observation() -> None:
    values = [0.0, 1.0, 2.0, 3.0, 100.0]
    result = _rolling_z(values, 4)
    assert result[:4] == [float("nan")] * 4
    assert result[4] > 1.0


def test_cftc_header_contract_is_resolved() -> None:
    header = [
        "Market and Exchange Names",
        "As of Date in Form YYMMDD",
        "As of Date in Form YYYY-MM-DD",
        "CFTC Contract Market Code",
        "Open Interest (All)",
        "Noncommercial Positions-Long (All)",
        "Noncommercial Positions-Short (All)",
    ]
    index, columns = _find_header([header, ["EURO FX", "260929", "2026-09-29", "099741", "100", "60", "20"]])
    assert index == 0
    assert columns["market"] == 0
    assert columns["date"] == 2
    assert columns["oi"] == 4
    assert columns["long"] == 5
    assert columns["short"] == 6


def test_parser_format_is_csv_inside_zip() -> None:
    body = io.StringIO()
    writer = csv.writer(body)
    writer.writerow([
        "Market and Exchange Names",
        "As of Date in Form YYMMDD",
        "As of Date in Form YYYY-MM-DD",
        "CFTC Contract Market Code",
        "Open Interest (All)",
        "Noncommercial Positions-Long (All)",
        "Noncommercial Positions-Short (All)",
    ])
    writer.writerow(["EURO FX - CHICAGO MERCANTILE EXCHANGE", "260929", "2026-09-29", "099741", "100", "60", "20"])
    payload = body.getvalue().encode()
    with zipfile.ZipFile(io.BytesIO(), "w") as archive:
        archive.writestr("deacot2026.txt", payload)
    assert payload.startswith(b"Market and Exchange Names")
