from __future__ import annotations

from datetime import date, timedelta

from research.cftc_positioning_certification import (
    FOLDS,
    MAX_PAIR_CONCENTRATION,
    MIN_RUN_OBSERVATIONS,
    TradeRecord,
    build_purged_folds,
    candidate_fingerprint,
)


def test_candidate_fingerprint_is_deterministic() -> None:
    candidate = {
        "feature_type": "level_z",
        "feature_window": 8,
        "threshold": 1.0,
        "orientation": "momentum",
        "horizon": 3,
    }
    assert candidate_fingerprint(candidate) == candidate_fingerprint(dict(candidate))


def test_purged_folds_are_chronological_and_remove_horizon_at_fold_start() -> None:
    days = [date(2020, 1, 6) + timedelta(days=index) for index in range(FOLDS * 8 + 8)]
    records = [
        TradeRecord(day, day + timedelta(days=2), "EUR/USD", 2.0)
        for day in days
    ]
    folds = build_purged_folds(records, days, horizon=3)
    assert len(folds) == FOLDS
    assert all(fold.records for fold in folds)
    for earlier, later in zip(folds, folds[1:]):
        assert earlier.start < later.start


def test_certification_defaults_are_strict() -> None:
    assert MIN_RUN_OBSERVATIONS >= 30
    assert 0 < MAX_PAIR_CONCENTRATION <= 0.80
