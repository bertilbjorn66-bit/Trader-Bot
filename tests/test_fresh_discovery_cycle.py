from __future__ import annotations

from research.fresh_discovery_cycle import DISTANCE_GRID, REGIMES, run_discovery


def test_discovery_grid_is_finite_and_confirmation_free() -> None:
    assert len(DISTANCE_GRID) == 5
    assert len(REGIMES) == 9


def test_discovery_report_is_structurally_one_way(monkeypatch) -> None:
    def fake_load_feed_bars(_path):
        return []

    def fake_analyze_pair(pair, rows, sample_stride, history_states, costs):
        return [], {"pair": pair, "rows": len(rows), "sample_stride": sample_stride, "history_states": history_states}

    import research.fresh_discovery_cycle as module

    monkeypatch.setattr(module, "load_feed_bars", fake_load_feed_bars)
    monkeypatch.setattr(module.experiment, "analyze_pair", fake_analyze_pair)

    report = run_discovery(__file__.__class__("."), 60, 10000)

    assert report["status"] == "FRESH_DISCOVERY_COMPLETED"
    assert report["selection_policy"]["confirmation_used_for_selection"] is False
    assert report["selection_policy"]["prior_frozen_confirmation_artifact_read"] is False
