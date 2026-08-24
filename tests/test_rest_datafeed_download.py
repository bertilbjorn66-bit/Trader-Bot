from datetime import timezone

from research.rest_datafeed_download import merge_sides, normalize, parse_dt


def test_normalize_removes_pair_separators() -> None:
    assert normalize("EUR/USD") == "EURUSD"
    assert normalize("usd-jpy") == "USDJPY"


def test_parse_dt_requires_timezone_and_normalizes_to_utc() -> None:
    parsed = parse_dt("2026-01-01T03:00:00+03:00")
    assert parsed.tzinfo == timezone.utc
    assert parsed.hour == 0


def test_merge_sides_keeps_only_common_timestamps() -> None:
    bid = [
        {"timestamp": 1000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05},
        {"timestamp": 2000, "open": 2.0, "high": 2.1, "low": 1.9, "close": 2.05},
    ]
    ask = [
        {"timestamp": 1000, "open": 1.01, "high": 1.11, "low": 0.91, "close": 1.06},
        {"timestamp": 3000, "open": 3.0, "high": 3.1, "low": 2.9, "close": 3.05},
    ]
    merged = merge_sides(bid, ask)
    assert merged == [
        {
            "timestamp": 1000,
            "bid_open": 1.0,
            "bid_high": 1.1,
            "bid_low": 0.9,
            "bid_close": 1.05,
            "ask_open": 1.01,
            "ask_high": 1.11,
            "ask_low": 0.91,
            "ask_close": 1.06,
        }
    ]
