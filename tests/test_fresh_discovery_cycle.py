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


def test_discovery_parallel_workers_are_positive_and_reported(monkeypatch) -> None:
    def fake_load_feed_bars(_path: Path):
        return []

    def fake_analyze_pair(pair, rows, sample_stride, history_states, costs):
        return [], {"pair": pair, "rows": len(rows), "sample_stride": sample_stride, "history_states": history_states}

    import research.fresh_discovery_cycle as module

    monkeypatch.setattr(module, "load_feed_bars", fake_load_feed_bars)
    monkeypatch.setattr(module, "_sha256_file", lambda _path: "0" * 64)
    monkeypatch.setattr(module.experiment, "analyze_pair", fake_analyze_pair)

    report = module.run_discovery(Path("."), 60, 10000, parallel_workers=1)
    assert report["selection_policy"]["parallel_workers"] == 1


def test_indexed_discovery_subsets_preserve_input_order() -> None:
    from research.fresh_discovery_cycle import _group_discovery_records

    def record(pair: str, minute: int) -> dict[str, object]:
        return {
            "pair": pair,
            "timestamp": f"2025-01-01T00:{minute:02d}:00+00:00",
            "year": 2025,
            "session": "london",
            "regime": "regime:trend_up",
            "direction": "long",
            "horizon": 6,
            "k": 10,
            "agreement": 0.8,
            "median_distance": 0.5,
            "distance_p10": 0.4,
            "distance_p90": 0.6,
            "outcome_pips": 1.0,
            "split": "discovery",
            "global_split": "discovery",
        }

    records = [
        record("EUR/USD", 0),
        record("GBP/USD", 1),
        record("USD/JPY", 2),
        record("EUR/USD", 3),
    ]
    grouped = _group_discovery_records(records)
    all_key = (6, "regime:trend_up", "london", "long", "discovery", "all")
    jpy_key = (6, "regime:trend_up", "london", "long", "discovery", "JPY")
    assert [item["pair"] for item in grouped[all_key]] == [item["pair"] for item in records]
    assert [item["pair"] for item in grouped[jpy_key]] == ["USD/JPY"]


def test_discovery_familywise_policy_is_predeclared() -> None:
    from research.fresh_discovery_cycle import DISCOVERY_HOLM_ALPHA

    assert DISCOVERY_HOLM_ALPHA == 0.05


def test_filtered_outcomes_share_evaluator_filter_semantics() -> None:
    from research.enriched_conditional_experiment import filtered_outcomes

    records = [
        {"split": "discovery", "median_distance": 0.4, "agreement": 0.8, "outcome_pips": 2.0},
        {"split": "discovery", "median_distance": 0.7, "agreement": 0.8, "outcome_pips": 1.0},
        {"split": "confirmation", "median_distance": 0.4, "agreement": 0.8, "outcome_pips": -1.0},
    ]
    assert filtered_outcomes(records, distance_max=0.5, agreement_min=0.7, split="discovery") == [2.0]


def test_global_discovery_subset_is_not_retrimmed_by_pair_local_split() -> None:
    from research.enriched_conditional_experiment import filtered_outcomes

    records = [
        {"split": "confirmation", "global_split": "discovery", "median_distance": 0.5, "agreement": 0.8, "outcome_pips": 2.0},
    ]
    assert filtered_outcomes(records, split="all") == [2.0]
    assert filtered_outcomes(records, split="discovery") == []


def test_discovery_familywise_holm_gate_blocks_unadjusted_signal(monkeypatch, tmp_path) -> None:
    import research.fresh_discovery_cycle as module

    records = []
    base_timestamp = __import__("datetime").datetime(2025, 1, 1, tzinfo=__import__("datetime").timezone.utc)
    for index in range(320):
        timestamp = base_timestamp + __import__("datetime").timedelta(minutes=10 * index)
        outcome = 1.0 if index < 150 else -0.5
        records.append({
            "pair": "EUR/USD",
            "timestamp": timestamp.isoformat(),
            "target_end_timestamp": (timestamp + __import__("datetime").timedelta(minutes=10)).isoformat(),
            "year": 2025,
            "session": "london",
            "regime": "regime:trend_up",
            "direction": "long",
            "horizon": 1,
            "k": 100,
            "agreement": 0.8,
            "median_distance": 0.5,
            "distance_p10": 0.4,
            "distance_p90": 0.6,
            "outcome_pips": outcome,
            "split": "discovery",
            "global_split": "",
        })

    for symbol in module.PAIR_TO_SYMBOL.values():
        (tmp_path / f"{symbol}.jsonl").write_text("", encoding="utf-8")

    def fake_analyze_pair(pair, feed_path, sample_stride, history_states, costs):
        pair_records = [dict(record, pair=pair) for record in records]
        return pair, pair_records, {"pair": pair}

    monkeypatch.setattr(module, "_analyze_pair_from_feed", fake_analyze_pair)
    monkeypatch.setattr(module, "_sha256_file", lambda _path: "0" * 64)
    monkeypatch.setattr(module, "DEFAULT_HORIZONS", (1,))
    monkeypatch.setattr(module, "AGREEMENT_GRID", (0.5,))
    monkeypatch.setattr(module, "DISTANCE_GRID", (None,))
    monkeypatch.setattr(module, "REGIMES", ("regime:trend_up",))
    monkeypatch.setattr(module, "SESSIONS", ("london",))
    monkeypatch.setattr(module, "PAIRSETS", ("all", "JPY"))
    monkeypatch.setattr(module, "DIRECTIONS", ("long",))
    monkeypatch.setattr(module, "hac_mean_pvalue", lambda _values: 0.04)

    report = module.run_discovery(tmp_path, 60, 10000, parallel_workers=1)
    assert report["selection_policy"]["discovery_family_size"] == 2
    assert report["candidate_count"] == 0
    assert report["bootstrap_near_misses"]
    assert all(item["discovery_family_size"] == 2 for item in report["bootstrap_near_misses"])
    assert all(
        item["near_miss_reason"] == "failed discovery-family Holm-adjusted HAC p-value"
        for item in report["bootstrap_near_misses"]
        if "near_miss_reason" in item
    )
