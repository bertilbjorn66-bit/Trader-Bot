from research.jetta_datafeed_download import aggregate_10m, parse_timestamp


def test_aggregate_10m_requires_complete_5m_pair() -> None:
    bars = [
        (0, 1.0, 1.2, 0.9, 1.1, 10.0),
        (300_000, 1.1, 1.3, 1.0, 1.2, 11.0),
        (600_000, 1.2, 1.4, 1.1, 1.3, 12.0),
    ]
    result = aggregate_10m(bars)
    assert result == [(0, 1.0, 1.3, 0.9, 1.2, 21.0)]


def test_parse_timestamp_accepts_milliseconds_seconds_and_iso() -> None:
    assert parse_timestamp("1612137600000") == 1612137600000
    assert parse_timestamp("1612137600") == 1612137600000
    assert parse_timestamp("2021-02-01T00:00:00+00:00") == 1612137600000
    assert parse_timestamp("2021-02-01T00:00:00Z") == 1612137600000
