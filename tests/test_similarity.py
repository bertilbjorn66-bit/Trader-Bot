from datetime import datetime, timedelta, timezone

from research.similarity import SimilarityIndex, fit_scaler
from research.types import State


def _states(count: int = 20) -> list[State]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        State(
            timestamp=start + timedelta(minutes=index),
            features={
                "trend": float(index) / 10.0,
                "trend_strength": float((index % 7) + 1),
            },
        )
        for index in range(count)
    ]


def test_prefix_scaler_matches_reference_scaler() -> None:
    states = _states()
    index = SimilarityIndex(states, ("trend", "trend_strength"))
    for start, end in ((0, 10), (3, 18), (5, 20)):
        expected = fit_scaler(states[start:end], ("trend", "trend_strength"))
        actual = index.fit_scaler(start, end)
        for name in expected:
            assert actual[name][0] == expected[name][0] or abs(actual[name][0] - expected[name][0]) < 1e-12
            assert abs(actual[name][1] - expected[name][1]) < 1e-10
