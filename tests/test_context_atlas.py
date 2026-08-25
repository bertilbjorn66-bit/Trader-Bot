from __future__ import annotations

from datetime import datetime, timezone

from research.context_atlas import build_atlas, enrich_record


def row(*, timestamp: str, outcome: float, pair: str = "EUR/USD", split: str = "confirmation") -> dict[str, object]:
    return {
        "pair": pair,
        "timestamp": timestamp,
        "year": datetime.fromisoformat(timestamp).year,
        "session": "london",
        "regime": "regime:trend_up",
        "direction": "long",
        "horizon": 6,
        "k": 100,
        "agreement": 0.75,
        "median_distance": 0.5,
        "outcome_pips": outcome,
        "split": split,
    }


def test_enrich_record_derives_temporal_and_quality_bands() -> None:
    result = enrich_record(row(timestamp="2024-02-05T12:00:00+00:00", outcome=1.0))
    assert result["weekday"] == "monday"
    assert result["hour_utc"] == 12
    assert result["agreement_band"] == "0.70-0.79"
    assert result["distance_band"] == "<=0.50"
    assert result["outcome_sign"] == "win"


def test_context_atlas_builds_confirmation_cells_and_pair_coverage() -> None:
    records = []
    for year in (2022, 2023, 2024):
        for month in range(1, 13):
            day = min(month, 28)
            timestamp = datetime(year, month, day, 12, tzinfo=timezone.utc).isoformat()
            records.append(row(timestamp=timestamp, outcome=1.0, split="confirmation"))
    result = build_atlas(records)
    assert result["status"] == "CONTEXT_ATLAS_COMPLETED"
    assert result["record_count"] == 36
    assert result["coverage"]["pairs"] == ["EUR/USD"]
    assert result["atlas_fingerprint"]
    assert result["confirmation_contexts"]["strong_contexts"]


def test_negative_context_is_explicitly_no_trade() -> None:
    records = []
    for index in range(30):
        year = 2022 + (index % 3)
        month = (index % 12) + 1
        records.append(
            row(
                timestamp=datetime(year, month, min((index % 27) + 1, 28), 12, tzinfo=timezone.utc).isoformat(),
                outcome=-0.5,
                split="confirmation",
            )
        )
    result = build_atlas(records)
    no_trade = result["confirmation_contexts"]["no_trade_contexts"]
    assert no_trade
    assert no_trade[0]["stats"]["status"] == "NO_TRADE"


def test_non_timezone_timestamp_is_rejected() -> None:
    bad = row(timestamp="2024-02-05T12:00:00", outcome=1.0)
    try:
        enrich_record(bad)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("timezone-naive timestamp should fail")
