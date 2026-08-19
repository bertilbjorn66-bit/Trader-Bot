import json
from pathlib import Path

from research.datafeed_empirical import load_feed_bars


def test_load_feed_bars_flattens_month_records_and_sorts(tmp_path: Path) -> None:
    path = tmp_path / "eurusd.jsonl"
    path.write_text(
        json.dumps({"month_start": "2020-02-01T00:00:00Z", "bars": [{"timestamp": 2000}]})
        + "\n"
        + json.dumps({"month_start": "2020-01-01T00:00:00Z", "bars": [{"timestamp": 1000}]})
        + "\n",
        encoding="utf-8",
    )
    rows = load_feed_bars(path)
    assert [row["timestamp"] for row in rows] == [1000, 2000]
