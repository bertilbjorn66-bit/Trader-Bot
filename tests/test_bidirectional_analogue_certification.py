from __future__ import annotations

from datetime import datetime, timedelta, timezone

from research.bidirectional_analogue_certification import build_purged_folds, certify

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(index: int) -> dict[str, object]:
    return {
        "timestamp": (BASE + timedelta(minutes=10 * index)).isoformat(),
        "target_end_timestamp": (BASE + timedelta(minutes=20 + 10 * index)).isoformat(),
        "global_split": "confirmation",
        "horizon": 2,
        "k": 25,
        "direction": "long",
        "pair": "EUR/USD",
        "outcome_pips": 1.0,
    }


def test_purged_folds_respect_horizon_and_next_boundary() -> None:
    records = [_record(index) for index in range(48)]
    folds = build_purged_folds(records, horizon=2, timeline_records=records)
    assert len(folds) == 12
    for fold in folds:
        assert all(
            record_timestamp >= fold.start + timedelta(minutes=20)
            for record_timestamp in (
                datetime.fromisoformat(str(record["timestamp"]))
                for record in fold.records
            )
        )
        if fold.end is not None:
            assert all(
                datetime.fromisoformat(str(record["timestamp"])) + timedelta(minutes=20)
                < fold.end
                for record in fold.records
            )
        assert fold.purged_at_start >= 0
        assert fold.purged_at_end >= 0


def test_certification_blocks_when_confirmation_did_not_pass() -> None:
    discovery = {
        "status": "BIDIRECTIONAL_ANALOGUE_DISCOVERY_COMPLETED",
        "selection_policy": {"contract_version": "v1-bidirectional-analogue-familywise"},
    }
    confirmation = {
        "confirmation_contract_version": "v1-bidirectional-analogue-confirmation",
        "state": "FAIL",
    }
    result = certify(discovery, confirmation, [])
    assert result["state"] == "INCOMPLETE"
    assert result["promotion_authorized"] is False
    assert result["live_execution_authorized"] is False
