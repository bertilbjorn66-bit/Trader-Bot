import json
from pathlib import Path

from research.data_connected_intelligence import build_data_connected_intelligence


def test_data_connected_intelligence_builds_descriptive_artifact(tmp_path: Path) -> None:
    records = []
    for timestamp in range(40):
        for pair, sign in (("EUR/USD", 1.0), ("GBP/USD", 0.8), ("USD/JPY", -0.4)):
            records.append(
                {
                    "pair": pair,
                    "timestamp": f"2020-01-01T00:{timestamp:02d}:00+00:00",
                    "year": 2020,
                    "session": "london",
                    "regime": "regime:trend",
                    "direction": "long",
                    "horizon": 1,
                    "agreement": 0.6,
                    "outcome_pips": sign,
                    "split": "discovery" if timestamp < 24 else "confirmation",
                }
            )
    source = tmp_path / "holdout.json"
    output = tmp_path / "atlas.json"
    source.write_text(json.dumps({"target_records": records}), encoding="utf-8")
    result = build_data_connected_intelligence(source, output)
    assert result["status"] == "DATA_CONNECTED_INTELLIGENCE_ATLAS_COMPLETED"
    assert result["record_count"] == len(records)
    assert result["promotion"]["live_authorization"] is False
    assert result["cross_pair_relations"]
    assert result["regime_transitions"]
    assert result["agreement_calibration"]
    assert result["cost_stress"]
    assert result["discovery_vs_confirmation_drift"]
