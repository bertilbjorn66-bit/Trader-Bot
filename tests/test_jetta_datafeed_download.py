from research.jetta_datafeed_download import aggregate_10m


def test_aggregate_10m_requires_complete_5m_pair() -> None:
    bars = [
        (0, 1.0, 1.2, 0.9, 1.1, 10.0),
        (300_000, 1.1, 1.3, 1.0, 1.2, 11.0),
        (600_000, 1.2, 1.4, 1.1, 1.3, 12.0),
    ]
    result = aggregate_10m(bars)
    assert result == [(0, 1.0, 1.3, 0.9, 1.2, 21.0)]
