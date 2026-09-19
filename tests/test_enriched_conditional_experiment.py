from __future__ import annotations

from datetime import datetime, timedelta, timezone

from research.enriched_conditional_experiment import (
    _is_contiguous_window,
    assign_global_split,
    evaluate,
    wilson_interval,
)


def test_wilson_interval_is_bounded() -> None:
    low, high = wilson_interval(0.5, 200)
    assert low is not None and high is not None
    assert 0.0 < low < 0.5 < high < 1.0


def test_evaluate_applies_distance_and_agreement_filters() -> None:
    records = [
        {"split": "discovery", "median_distance": 0.4, "agreement": 0.8, "outcome_pips": 2.0},
        {"split": "discovery", "median_distance": 0.7, "agreement": 0.8, "outcome_pips": 1.0},
        {"split": "discovery", "median_distance": 0.4, "agreement": 0.4, "outcome_pips": -5.0},
        {"split": "confirmation", "median_distance": 0.4, "agreement": 0.8, "outcome_pips": -1.0},
    ]
    result = evaluate(records, distance_max=0.5, agreement_min=0.7, split="discovery")
    assert result is not None
    assert result["n"] == 1
    assert result["expectancy_pips"] == 2.0
    assert result["win_rate"] == 1.0


def test_confirmation_is_separate_from_discovery() -> None:
    records = [
        {"split": "discovery", "median_distance": 0.2, "agreement": 0.8, "outcome_pips": 3.0},
        {"split": "confirmation", "median_distance": 0.2, "agreement": 0.8, "outcome_pips": -2.0},
    ]
    discovery = evaluate(records, agreement_min=0.7, split="discovery")
    confirmation = evaluate(records, agreement_min=0.7, split="confirmation")
    assert discovery is not None and confirmation is not None
    assert discovery["expectancy_pips"] == 3.0
    assert confirmation["expectancy_pips"] == -2.0


def test_continuity_rejects_weekend_or_missing_bar_gaps() -> None:
    base = datetime(2026, 1, 2, 23, 0, tzinfo=timezone.utc)

    class BarStub:
        def __init__(self, timestamp: datetime) -> None:
            self.timestamp = timestamp

    contiguous = [BarStub(base + i * timedelta(minutes=10)) for i in range(4)]
    gapped = [contiguous[0], contiguous[1], BarStub(base + timedelta(minutes=40)), contiguous[3]]
    assert _is_contiguous_window(contiguous, 0, 3)
    assert not _is_contiguous_window(gapped, 0, 3)


def test_global_split_requires_complete_outcome_before_cutoff() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = []
    for index in range(10):
        start = base + timedelta(minutes=10 * index)
        end = start + timedelta(minutes=10)
        records.append({
            "timestamp": start.isoformat(),
            "target_end_timestamp": end.isoformat(),
            "global_split": "",
        })
    cutoff = assign_global_split(records)
    assert cutoff == (base + timedelta(minutes=60)).isoformat()
    assert all(record["global_split"] == "discovery" for record in records[:5])
    assert all(record["global_split"] == "confirmation" for record in records[5:])


def test_global_split_purges_target_crossing_cutoff_even_when_start_is_earlier() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = []
    for index in range(10):
        start = base + timedelta(minutes=10 * index)
        end = start + timedelta(minutes=40 if index == 4 else 10)
        records.append({
            "timestamp": start.isoformat(),
            "target_end_timestamp": end.isoformat(),
            "global_split": "",
        })
    cutoff = assign_global_split(records)
    assert cutoff == (base + timedelta(minutes=50)).isoformat()
    assert records[4]["global_split"] == "confirmation"
    assert records[3]["global_split"] == "discovery"
