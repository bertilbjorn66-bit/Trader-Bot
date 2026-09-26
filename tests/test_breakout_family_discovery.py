from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from research.breakout_family_discovery import (
    BREAKOUT_BUFFERS_ATR,
    HORIZONS,
    LOOKBACKS,
    _all_candidates,
    _split,
    run_discovery,
)


def test_breakout_family_is_finite_and_expected_size() -> None:
    candidates = _all_candidates()
    assert len(candidates) == (
        len(LOOKBACKS) * len(BREAKOUT_BUFFERS_ATR) * len(HORIZONS)
    )
    assert len(candidates) == 48


def test_split_purges_crossing_horizons() -> None:
    cutoff = datetime(2026, 1, 3, 0, 40, tzinfo=timezone.utc)
    assert _split(cutoff - timedelta(minutes=20), 1, cutoff) == "discovery"
    assert _split(cutoff - timedelta(minutes=20), 2, cutoff) == "purged_boundary"
    assert _split(cutoff, 6, cutoff) == "confirmation"


def test_missing_input_is_rejected(tmp_path: Path) -> None:
    try:
        run_discovery(tmp_path)
    except FileNotFoundError as exc:
        assert "missing verified feed" in str(exc)
    else:
        raise AssertionError("missing feed should fail closed")
