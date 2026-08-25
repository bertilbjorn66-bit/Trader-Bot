from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import research.enriched_conditional_experiment as experiment
from research.datafeed_empirical import PAIR_TO_SYMBOL, load_feed_bars
from research.execution import ExecutionAssumptions
from research.sequential_empirical import DEFAULT_HORIZONS


AGREEMENT_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75)
DISTANCE_GRID: tuple[float | None, ...] = (None, 0.5, 1.0, 1.5, 2.0)
REGIMES = (
    "regime:breakout_up",
    "regime:breakout_down",
    "regime:high_vol_trend_up",
    "regime:high_vol_trend_down",
    "regime:high_volatility_range",
    "regime:trend_up",
    "regime:trend_down",
    "regime:range_low_vol",
    "regime:range_normal",
)
SESSIONS = ("asia", "london", "new_york", "overlap")
PAIRSETS = ("all", "JPY")
MIN_DISCOVERY_SAMPLES = 150
TOP_N = 25


def _candidate_key(candidate: dict[str, Any]) -> tuple[float, float, int]:
    discovery = candidate["discovery"]
    return (
        float(discovery["expectancy_pips"]),
        float(discovery["profit_factor"] or -math.inf),
        int(discovery["n"]),
    )


def run_discovery(input_dir: Path, sample_stride: int, history_states: int) -> dict[str, Any]:
    if sample_stride <= 0 or history_states <= 0:
        raise ValueError("sample_stride and history_states must be positive")

    costs = ExecutionAssumptions()
    all_records: list[dict[str, Any]] = []
    quality: dict[str, Any] = {}
    for pair in PAIR_TO_SYMBOL:
        records, pair_quality = experiment.analyze_pair(
            pair,
            load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"),
            sample_stride,
            history_states,
            costs,
        )
        all_records.extend(records)
        quality[pair] = pair_quality

    candidates: list[dict[str, Any]] = []
    for horizon in DEFAULT_HORIZONS:
        for agreement_min in AGREEMENT_GRID:
            for distance_max in DISTANCE_GRID:
                for regime in REGIMES:
                    for session in SESSIONS:
                        for pairset in PAIRSETS:
                            subset = [
                                record
                                for record in all_records
                                if record["horizon"] == horizon
                                and record["split"] == "discovery"
                                and record["regime"] == regime
                                and record["session"] == session
                                and (pairset == "all" or record["pair"].endswith("/JPY"))
                            ]
                            result = experiment.evaluate(
                                subset,
                                distance_max,
                                agreement_min,
                                "discovery",
                                with_bootstrap=True,
                            )
                            if result is None or result["n"] < MIN_DISCOVERY_SAMPLES:
                                continue
                            candidates.append(
                                {
                                    "horizon": horizon,
                                    "agreement_min": agreement_min,
                                    "distance_max": distance_max,
                                    "regime": regime,
                                    "session": session,
                                    "pairset": pairset,
                                    "discovery": result,
                                }
                            )

    candidates.sort(key=_candidate_key, reverse=True)
    selected = candidates[:TOP_N]
    return {
        "status": "FRESH_DISCOVERY_COMPLETED",
        "selection_policy": {
            "source": "verified nine-pair historical feed",
            "split": "chronological discovery segment only",
            "minimum_discovery_samples": MIN_DISCOVERY_SAMPLES,
            "candidate_grid": {
                "horizons": list(DEFAULT_HORIZONS),
                "agreement_min": list(AGREEMENT_GRID),
                "distance_max": list(DISTANCE_GRID),
                "regimes": list(REGIMES),
                "sessions": list(SESSIONS),
                "pairsets": list(PAIRSETS),
            },
            "ranking": "discovery expectancy, then discovery profit factor, then sample count",
            "confirmation_used_for_selection": False,
            "prior_frozen_confirmation_artifact_read": False,
        },
        "record_count": len(all_records),
        "candidate_count": len(candidates),
        "top_candidates": selected,
        "data_quality": quality,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a fresh discovery-only conditional-edge search.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    args = parser.parse_args()

    report = run_discovery(Path(args.input_dir), args.sample_stride, args.history_states)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
