from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import TypedDict

from . import sequential_empirical as empirical
from .cross_section import session_label
from .datafeed_empirical import PAIR_TO_SYMBOL, _execution_valid_rows, _market_bars, load_feed_bars
from .execution import ExecutionAssumptions, net_move
from .outcomes import future_outcome
from .pipeline import state_from_bar_window
from .regimes import classify_regime
from .similarity import DEFAULT_FEATURES, fit_scaler, nearest_states
from .types import State

PAIR_PIP = {
    "EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01,
    "AUD/USD": 0.0001, "USD/CAD": 0.0001, "USD/CHF": 0.0001,
    "NZD/USD": 0.0001, "EUR/JPY": 0.01, "GBP/JPY": 0.01,
}


class EvalResult(TypedDict):
    n: int
    expectancy_pips: float
    profit_factor: float | None
    win_rate: float
    win_rate_ci: list[float | None]
    bootstrap_expectancy_ci_pips: list[float | None]
    median_outcome_pips: float


class TargetRecord(TypedDict):
    pair: str
    timestamp: str
    year: int
    session: str
    regime: str
    direction: str
    horizon: int
    k: int
    agreement: float
    median_distance: float
    distance_p10: float | None
    distance_p90: float | None
    outcome_pips: float
    split: str


class Candidate(TypedDict, total=False):
    horizon: int
    agreement_min: float
    distance_max: float | None
    regime: str
    session: str
    pairset: str
    discovery: EvalResult
    discovery_bootstrap: EvalResult | None
    confirmation: EvalResult | None


def numeric_feature(state: State, name: str) -> float:
    value = state.features.get(name)
    if not isinstance(value, (float, int)):
        raise ValueError(f"state feature {name!r} must be numeric")
    return float(value)


def integer_feature(state: State, name: str) -> int:
    value = state.features.get(name)
    if not isinstance(value, int):
        raise ValueError(f"state feature {name!r} must be an integer")
    return value


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_ci(values: list[float], repetitions: int = 1000, seed: int = 20260821) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    rng = random.Random(seed)
    means = [mean(values[rng.randrange(len(values))] for _ in values) for _ in range(repetitions)]
    means.sort()
    return means[int(0.025 * repetitions)], means[int(0.975 * repetitions) - 1]


def wilson_interval(win_rate: float, n: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    denominator = 1.0 + (z * z / n)
    centre = (win_rate + z * z / (2.0 * n)) / denominator
    half = z * math.sqrt((win_rate * (1.0 - win_rate) / n) + (z * z / (4.0 * n * n))) / denominator
    return centre - half, centre + half


def evaluate(
    records: list[TargetRecord],
    distance_max: float | None = None,
    agreement_min: float = 0.0,
    split: str = "all",
    with_bootstrap: bool = False,
) -> EvalResult | None:
    values = [
        record["outcome_pips"]
        for record in records
        if (split == "all" or record["split"] == split)
        and (distance_max is None or record["median_distance"] <= distance_max)
        and record["agreement"] >= agreement_min
    ]
    if not values:
        return None
    wins = sum(value > 0.0 for value in values)
    gross_wins = sum(value for value in values if value > 0.0)
    gross_losses = -sum(value for value in values if value < 0.0)
    win_rate = wins / len(values)
    low, high = wilson_interval(win_rate, len(values))
    bootstrap_low, bootstrap_high = bootstrap_ci(values) if with_bootstrap else (None, None)
    return {
        "n": len(values),
        "expectancy_pips": mean(values),
        "profit_factor": gross_wins / gross_losses if gross_losses else None,
        "win_rate": win_rate,
        "win_rate_ci": [low, high],
        "bootstrap_expectancy_ci_pips": [bootstrap_low, bootstrap_high],
        "median_outcome_pips": median(values),
    }


def analyze_pair(
    pair: str,
    rows: list[dict[str, object]],
    sample_stride: int,
    history_states: int,
    costs: ExecutionAssumptions,
) -> tuple[list[TargetRecord], dict[str, object]]:
    rows, quality = _execution_valid_rows(rows, pair)
    bid, ask = _market_bars(rows)
    bars = empirical._merge(bid, ask)
    horizons = empirical.DEFAULT_HORIZONS
    minimum = empirical.STATE_LOOKBACK + history_states + max(horizons) + 10
    if len(bars) < minimum:
        raise ValueError(f"insufficient bars for {pair}: {len(bars)} < {minimum}")
    states = [state_from_bar_window(bars, index, empirical.STATE_LOOKBACK) for index in range(empirical.STATE_LOOKBACK, len(bars))]
    state_index = {state.timestamp: index + empirical.STATE_LOOKBACK for index, state in enumerate(states)}
    targets: list[TargetRecord] = []

    for position in range(history_states, len(states), sample_stride):
        target = states[position]
        target_index = state_index[target.timestamp]
        if target_index + max(horizons) >= len(bars):
            continue
        history = states[position - history_states:position]
        scaler = fit_scaler(history, DEFAULT_FEATURES)
        nearest = nearest_states(target, history, scaler, k=min(100, len(history)))
        neighbors: list[tuple[State, float]] = []
        for state, distance in nearest:
            state_index_value = state_index[state.timestamp]
            # Require the entire analogue outcome window to finish strictly before
            # the target bar. Allowing equality would leak target-bar market data.
            if any(state_index_value + horizon >= target_index for horizon in horizons):
                continue
            neighbors.append((state, distance))
        if not neighbors:
            continue

        direction = "long" if numeric_feature(target, "momentum") >= 0.0 else "short"
        regime = classify_regime(
            numeric_feature(target, "trend"),
            numeric_feature(target, "trend_strength"),
            empirical._volatility_z(target, history),
            integer_feature(target, "breakout"),
        )
        distances = [distance for _, distance in neighbors]
        for horizon in horizons:
            evidence = [
                net_move(future_outcome(bars, state_index[neighbor.timestamp], horizon, direction).return_abs, costs)
                for neighbor, _ in neighbors
            ]
            if not evidence:
                continue
            target_outcome = future_outcome(bars, target_index, horizon, direction)
            targets.append({
                "pair": pair,
                "timestamp": target.timestamp.isoformat(),
                "year": target.timestamp.year,
                "session": session_label(target.timestamp),
                "regime": f"regime:{regime}",
                "direction": direction,
                "horizon": horizon,
                "k": len(neighbors),
                "agreement": sum(value > 0.0 for value in evidence) / len(evidence),
                "median_distance": median(distances),
                "distance_p10": percentile(distances, 0.10),
                "distance_p90": percentile(distances, 0.90),
                "outcome_pips": net_move(target_outcome.return_abs, costs) / PAIR_PIP[pair],
                "split": "",
            })

    timestamps = sorted({datetime.fromisoformat(record["timestamp"]) for record in targets})
    cutoff = timestamps[int(len(timestamps) * 0.70)] if timestamps else None
    for record in targets:
        record["split"] = "discovery" if cutoff and datetime.fromisoformat(record["timestamp"]) < cutoff else "confirmation"
    return targets, quality


def main() -> None:
    parser = argparse.ArgumentParser(description="Enriched leakage-safe conditional-edge experiment from verified empirical feed files.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=120)
    parser.add_argument("--history-states", type=int, default=10000)
    args = parser.parse_args()
    if args.sample_stride <= 0 or args.history_states <= 0:
        raise SystemExit("sample-stride and history-states must be positive")

    costs = ExecutionAssumptions()
    all_records: list[TargetRecord] = []
    quality: dict[str, object] = {}
    input_dir = Path(args.input_dir)
    for pair in PAIR_TO_SYMBOL:
        records, pair_quality = analyze_pair(
            pair,
            load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"),
            args.sample_stride,
            args.history_states,
            costs,
        )
        all_records.extend(records)
        quality[pair] = pair_quality

    # Match the exact labels emitted by classify_regime(); do not silently omit
    # regimes from discovery because of naming drift.
    regimes = (
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
    sessions = ("asia", "london", "new_york", "overlap")
    candidates: list[Candidate] = []
    pairsets = ("all", "JPY")
    for horizon in empirical.DEFAULT_HORIZONS:
        for agreement_min in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
            for distance_max in (None, 0.5, 1.0, 1.5, 2.0):
                for regime in regimes:
                    for session in sessions:
                        for pairset in pairsets:
                            subset = [
                                record
                                for record in all_records
                                if record["horizon"] == horizon
                                and record["split"] == "discovery"
                                and record["regime"] == regime
                                and record["session"] == session
                                and (pairset == "all" or record["pair"].endswith("/JPY"))
                            ]
                            result = evaluate(subset, distance_max, agreement_min, "discovery")
                            if result is not None and result["n"] >= 100:
                                candidates.append({
                                    "horizon": horizon,
                                    "agreement_min": agreement_min,
                                    "distance_max": distance_max,
                                    "regime": regime,
                                    "session": session,
                                    "pairset": pairset,
                                    "discovery": result,
                                })

    candidates.sort(
        key=lambda candidate: (
            candidate["discovery"]["expectancy_pips"],
            candidate["discovery"]["profit_factor"] or -math.inf,
        ),
        reverse=True,
    )
    finalists = candidates[:10]
    for finalist in finalists:
        subset = [
            record
            for record in all_records
            if record["horizon"] == finalist["horizon"]
            and record["regime"] == finalist["regime"]
            and record["session"] == finalist["session"]
            and (finalist["pairset"] == "all" or record["pair"].endswith("/JPY"))
        ]
        finalist["discovery_bootstrap"] = evaluate(
            subset,
            finalist["distance_max"],
            finalist["agreement_min"],
            "discovery",
            with_bootstrap=True,
        )
        finalist["confirmation"] = evaluate(
            subset,
            finalist["distance_max"],
            finalist["agreement_min"],
            "confirmation",
        )

    output = {
        "status": "ENRICHED_CONDITIONAL_EXPERIMENT_COMPLETED",
        "market_data_accessed": True,
        "datasets_accessed": True,
        "sample_stride": args.sample_stride,
        "history_states": args.history_states,
        "record_count": len(all_records),
        "data_quality": quality,
        "target_records": all_records,
        "discovery_candidates": candidates[:100],
        "confirmation_finalists": finalists,
        "methodology": {
            "split": "chronological 70/30 discovery/confirmation within each pair",
            "candidate_search": "finite threshold grid, regime and session selected only on discovery data, then frozen",
            "analogue_k": 100,
            "leakage_rule": "an analogue's complete future outcome must end strictly before the target bar timestamp",
            "regime_search_space": list(regimes),
            "session_search_space": list(sessions),
            "outcome": "directional executable movement using BID/ASK, converted to pair-specific pips",
            "cost_model": "BID/ASK embedded; additional slippage and commission fixed at zero in this research artifact",
            "interpretation": "confirmation is the only segment eligible for strategy candidacy; discovery results are not deployment evidence",
        },
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
