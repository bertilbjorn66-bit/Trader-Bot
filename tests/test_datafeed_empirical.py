import json
import math
from pathlib import Path

import pytest

from research.datafeed_empirical import _execution_valid_rows, load_feed_bars


def _bar(timestamp: int) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "bid_open": 1.1,
        "bid_high": 1.101,
        "bid_low": 1.099,
        "bid_close": 1.1005,
        "ask_open": 1.1001,
        "ask_high": 1.1011,
        "ask_low": 1.0991,
        "ask_close": 1.1006,
    }


def test_load_feed_bars_flattens_month_records_and_sorts(tmp_path: Path) -> None:
    path = tmp_path / "eurusd.jsonl"
    path.write_text(
        json.dumps({"month_start": "2020-02-01T00:00:00Z", "bars": [_bar(2000)]})
        + "\n"
        + json.dumps({"month_start": "2020-01-01T00:00:00Z", "bars": [_bar(1000)]})
        + "\n",
        encoding="utf-8",
    )
    rows = load_feed_bars(path)
    assert [row["timestamp"] for row in rows] == [1000, 2000]


def test_load_feed_bars_accepts_canonical_bar_per_line_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "eurusd.jsonl"
    path.write_text(json.dumps(_bar(3000)) + "\n" + json.dumps(_bar(1000)) + "\n", encoding="utf-8")
    rows = load_feed_bars(path)
    assert [row["timestamp"] for row in rows] == [1000, 3000]


def test_execution_valid_rows_excludes_crossed_quote_bars() -> None:
    valid_rows = [_bar(timestamp) for timestamp in range(1000, 2000)]
    crossed = _bar(2000)
    crossed["ask_close"] = 1.0999
    rows, quality = _execution_valid_rows(valid_rows + [crossed], "EUR/USD")
    assert [row["timestamp"] for row in rows] == list(range(1000, 2000))
    assert quality["crossed_execution_bars_excluded"] == 1
    assert quality["input_bars"] == 1001


def test_load_feed_bars_rejects_invalid_ohlc_geometry(tmp_path: Path) -> None:
    path = tmp_path / "eurusd.jsonl"
    row = _bar(1000)
    row["bid_high"] = 1.099
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid BID OHLC geometry"):
        load_feed_bars(path)


def test_load_feed_bars_rejects_non_finite_price(tmp_path: Path) -> None:
    path = tmp_path / "eurusd.jsonl"
    row = _bar(1000)
    row["ask_close"] = math.nan
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="finite and strictly positive"):
        load_feed_bars(path)


def test_load_feed_bars_rejects_non_positive_price(tmp_path: Path) -> None:
    path = tmp_path / "eurusd.jsonl"
    row = _bar(1000)
    row["bid_low"] = 0.0
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="finite and strictly positive"):
        load_feed_bars(path)


def test_load_feed_bars_rejects_fractional_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "eurusd.jsonl"
    row = _bar(1000)
    row["timestamp"] = 1000.5
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="finite integer number of milliseconds"):
        load_feed_bars(path)


def test_load_feed_bars_rejects_non_positive_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "eurusd.jsonl"
    row = _bar(0)
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="timestamp must be strictly positive"):
        load_feed_bars(path)
