from datetime import datetime, timedelta, timezone

import pytest

from research.purged_walk_forward_certification import (
    EXECUTION_MODELS,
    FOLDS,
    MIN_RUN_TRADES,
    _candidate_fingerprint,
    _execution_values,
    _stats,
    build_purged_folds,
    certify,
    hac_mean_pvalue,
)


def _record(ts: datetime, pair: str = "EUR/USD", outcome: float = 2.0, horizon: int = 6) -> dict[str, object]:
    return {
        "pair": pair,
        "timestamp": ts.isoformat(),
        "horizon": horizon,
        "regime": "regime:trend_up",
        "session": "london",
        "direction": "long",
        "median_distance": 0.5,
        "agreement": 0.8,
        "outcome_pips": outcome,
        "split": "confirmation",
        "target_end_timestamp": (ts + timedelta(minutes=horizon * 10)).isoformat(),
        "global_split": "confirmation",
    }


def _candidate() -> dict[str, object]:
    return {
        "horizon": 6,
        "agreement_min": 0.75,
        "distance_max": 1.0,
        "regime": "regime:trend_up",
        "session": "london",
        "pairset": "all",
        "direction": "long",
        "discovery": {
            "n": 200,
            "expectancy_pips": 1.0,
            "profit_factor": 1.5,
            "win_rate": 0.65,
            "win_rate_ci": [0.58, 0.72],
            "bootstrap_expectancy_ci_pips": [0.4, 1.6],
            "median_outcome_pips": 0.8,
        },
    }


def _discovery() -> dict[str, object]:
    return {
        "status": "FRESH_DISCOVERY_COMPLETED",
        "selection_policy": {
            "contract_version": "v4-global-horizon-aware-two-stage-screen",
            "confirmation_used_for_selection": False,
            "prior_frozen_confirmation_artifact_read": False,
        },
        "global_split_cutoff": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=200)).isoformat(),
        "orchestration_binding": {
            "discovery_head_sha": "a" * 40,
            "discovery_run_id": 123,
            "source_run_id": 456,
            "sample_stride": 60,
            "history_states": 10000,
        },
        "top_candidates": [_candidate()],
    }


def _confirmation() -> dict[str, object]:
    candidate = _candidate()
    identity = {
        "horizon": candidate["horizon"],
        "agreement_min": candidate["agreement_min"],
        "distance_max": candidate["distance_max"],
        "regime": candidate["regime"],
        "session": candidate["session"],
        "pairset": candidate["pairset"],
        "direction": candidate["direction"],
    }
    return {
        "state": "PASS",
        "candidate": {**identity, "rank": 1},
        "candidate_fingerprint": _candidate_fingerprint(candidate),
        "global_split_cutoff": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=200)).isoformat(),
        "orchestration_binding": {
            "discovery_run_id": 123,
            "discovery_head_sha": "a" * 40,
            "confirmation_run_id": 789,
            "confirmation_head_sha": "b" * 40,
            "discovery_run_id": 123,
            "source_run_id": 456,
            "sample_stride": 60,
            "history_states": 10000,
        },
    }


def test_purged_folds_remove_start_and_cross_boundary_records() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = [_record(base + timedelta(minutes=10 * index)) for index in range(40)]
    folds = build_purged_folds(records, horizon=6, folds=12)

    assert len(folds) == 12
    assert all(fold.purged_at_start >= 1 for fold in folds[1:])
    for fold in folds[:-1]:
        assert fold.end is not None
        assert all(
            datetime.fromisoformat(str(record["timestamp"])) + timedelta(minutes=60)
            < fold.end
            for record in fold.records
        )


def test_build_folds_rejects_inadequate_timestamp_cardinality() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = [_record(base + timedelta(minutes=10 * index)) for index in range(3)]
    assert build_purged_folds(records, horizon=6, folds=4) == []


def test_execution_models_are_fixed_and_strictly_increasing() -> None:
    assert len(EXECUTION_MODELS) >= 3
    costs = [model.total_cost_pips() for _, model in EXECUTION_MODELS]
    assert costs == sorted(costs)
    net = [_execution_values([_record(datetime(2026, 1, 1, tzinfo=timezone.utc), outcome=2.0)], model)[0] for _, model in EXECUTION_MODELS]
    assert net[0] > net[1] > net[2]


def test_hac_pvalue_distinguishes_clear_positive_edge() -> None:
    assert hac_mean_pvalue([1.0] * 500) == 0.0
    assert hac_mean_pvalue([-1.0] * 500) == 1.0


def test_stats_require_recovery_from_drawdown() -> None:
    values = [2.0, 2.0, -1.0]
    stats = _stats(values)
    assert stats["net_profit_pips"] == pytest.approx(3.0)
    assert stats["max_drawdown_pips"] == pytest.approx(1.0)
    assert stats["recovery_ratio"] == pytest.approx(3.0)


def test_certification_blocks_when_confirmation_does_not_pass() -> None:
    result = certify(
        _discovery(),
        {"state": "FAIL", "promotion_authorized": False, "live_execution_authorized": False},
        [],
    )
    assert result["state"] == "INCOMPLETE"
    assert result["promotion_authorized"] is False
    assert result["live_execution_authorized"] is False


def test_certification_never_uses_an_alternate_candidate() -> None:
    discovery = _discovery()
    second = dict(_candidate())
    second["agreement_min"] = 0.70
    discovery["top_candidates"] = [_candidate(), second]
    confirmation = _confirmation()
    confirmation["candidate"] = {**confirmation["candidate"], "agreement_min": 0.70}
    with pytest.raises(ValueError, match="does not match"):
        certify(discovery, confirmation, [])


def test_run_trade_contract_is_explicit() -> None:
    assert MIN_RUN_TRADES == 500
    assert FOLDS == 12


def test_certification_rejects_candidate_fingerprint_mismatch() -> None:
    confirmation = _confirmation()
    confirmation["candidate_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        certify(_discovery(), confirmation, [])


def test_fold_boundaries_can_be_anchored_to_full_confirmation_timeline() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timeline = [_record(base + timedelta(minutes=10 * index)) for index in range(120)]
    sparse = timeline[::7]
    folds = build_purged_folds(sparse, horizon=6, folds=12, timeline_records=timeline)
    assert len(folds) == 12
    assert folds[0].start == base
    assert folds[-1].end is None
    for fold in folds[:-1]:
        assert fold.end is not None
        assert all(
            datetime.fromisoformat(str(record["timestamp"])) + timedelta(minutes=60)
            < fold.end
            for record in fold.records
        )


def test_certification_rejects_orchestration_binding_mismatch() -> None:
    confirmation = _confirmation()
    confirmation["orchestration_binding"] = {
        **confirmation["orchestration_binding"],
        "source_run_id": 999,
    }
    with pytest.raises(ValueError, match="orchestration binding mismatch"):
        certify(_discovery(), confirmation, [])


def test_certification_returns_incomplete_for_unevaluable_sparse_runs() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = [_record(base + timedelta(minutes=10 * index)) for index in range(24)]
    confirmation = _confirmation()
    result = certify(_discovery(), confirmation, records)
    assert result["state"] == "INCOMPLETE"
    assert result["promotion_authorized"] is False
    assert result["live_execution_authorized"] is False
    assert "fold_observation_counts" in result

def test_certification_boundaries_use_confirmation_timeline_only() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    discovery = []
    confirmation = []
    for index in range(120):
        ts = base + timedelta(minutes=10 * index)
        record = _record(ts)
        if index < 60:
            record["global_split"] = "discovery"
            discovery.append(record)
        else:
            record["global_split"] = "confirmation"
            confirmation.append(record)
    candidate_records = confirmation
    timeline = discovery + confirmation
    folds = build_purged_folds(candidate_records, horizon=6, folds=12, timeline_records=confirmation)
    wrong = build_purged_folds(candidate_records, horizon=6, folds=12, timeline_records=timeline)
    assert len(folds) == len(wrong) == 12
    assert folds[0].start == datetime.fromisoformat(str(confirmation[0]["timestamp"]))
    assert wrong[0].start == datetime.fromisoformat(str(discovery[0]["timestamp"]))
    assert folds[0].start > wrong[0].start


def test_certification_rejects_missing_confirmation_run_identity() -> None:
    confirmation = _confirmation()
    del confirmation["orchestration_binding"]["confirmation_run_id"]
    with pytest.raises(ValueError, match="confirmation_run_id"):
        certify(_discovery(), confirmation, [])
