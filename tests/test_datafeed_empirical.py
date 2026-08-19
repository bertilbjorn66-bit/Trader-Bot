import json
from pathlib import Path

from research.datafeed_empirical import load_feed_bars


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
