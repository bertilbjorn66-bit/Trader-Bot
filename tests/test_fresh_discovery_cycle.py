from __future__ import annotations

import hashlib
from pathlib import Path

from research.fresh_discovery_cycle import (
    DISTANCE_GRID,
    REGIMES,
    discovery_result_is_admissible,
    run_discovery,
)


def test_discovery_grid_is_finite_and_confirmation_free() -> None:
    from research.fresh_discovery_cycle import DIRECTIONS, PAIRSETS

    assert len(DISTANCE_GRID) == 5
    assert len(REGIMES) == 9
    assert DIRECTIONS == ("long", "short")
    assert PAIRSETS == ("all", "JPY")


def test_discovery_screen_requires_sample_pf_and_positive_bootstrap_lower_tail() -> None:
    base = {
        "n": 150,
        "expectancy_pips": 0.5,
        "profit_factor": 1.10,
        "win_rate": 0.55,
        "win_rate_ci": [0.47, 0.63],
        "bootstrap_expectancy_ci_pips": [0.01, 0.9],
        "median_outcome_pips": 0.4,
    }
    assert discovery_result_is_admissible(base)
    assert not discovery_result_is_admissible({**base, "n": 149})
    assert not discovery_result_is_admissible({**base, "profit_factor": 1.09})
    assert not discovery_result_is_admissible({**base, "bootstrap_expectancy_ci_pips": [-0.01, 0.9]})


def test_discovery_report_is_structurally_one_way(monkeypatch) -> None:
    def fake_load_feed_bars(_path: Path):
        return []

    def fake_analyze_pair(pair, rows, sample_stride, history_states, costs):
        return [], {"pair": pair, "rows": len(rows), "sample_stride": sample_stride, "history_states": history_states}

    import research.fresh_discovery_cycle as module

    monkeypatch.setattr(module, "load_feed_bars", fake_load_feed_bars)
    monkeypatch.setattr(module, "_sha256_file", lambda _path: "0" * 64)
    monkeypatch.setattr(module.experiment, "analyze_pair", fake_analyze_pair)

    report = run_discovery(Path("."), 60, 10000)

    assert report["status"] == "FRESH_DISCOVERY_COMPLETED"
    assert report["selection_policy"]["confirmation_used_for_selection"] is False
    assert report["selection_policy"]["prior_frozen_confirmation_artifact_read"] is False
    assert report["selection_policy"]["minimum_discovery_profit_factor"] == 1.10
    assert report["selection_policy"]["minimum_discovery_bootstrap_lower_expectancy_pips"] == 0.0
    assert report["selection_policy"]["candidate_grid"]["directions"] == ["long", "short"]
    assert report["selection_policy"]["bootstrap_near_miss_policy"].startswith("diagnostic only")
    assert "bootstrap_near_misses" in report


def test_sha256_file_is_deterministic(tmp_path) -> None:
    from research.fresh_discovery_cycle import _sha256_file

    path = tmp_path / "feed.jsonl"
    payload = b'{"timestamp":1,"bid_open":1,"bid_high":1,"bid_low":1,"bid_close":1,"ask_open":1,"ask_high":1,"ask_low":1,"ask_close":1}\n'
    path.write_bytes(payload)
    assert _sha256_file(path) == hashlib.sha256(payload).hexdigest()
