from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

from trader_bot.models import Timeframe

from . import sequential_empirical as empirical
from .cross_section import session_label
from .datafeed_empirical import PAIR_TO_SYMBOL, _execution_valid_rows, _market_bars, load_feed_bars
from .execution import ExecutionAssumptions, net_move
from .outcomes import future_outcome
from .pipeline import state_from_bar_window
from .regimes import classify_regime
from .similarity import DEFAULT_FEATURES, fit_scaler, nearest_states

PAIR_PIP = {
    "EUR/USD": 0.0001,
    "GBP/USD": 0.0001,
    "USD/JPY": 0.01,
    "AUD/USD": 0.0001,
    "USD/CAD": 0.0001,
    "USD/CHF": 0.0001,
    "NZD/USD": 0.0001,
    "EUR/JPY": 0.01,
    "GBP/JPY": 0.01,
}


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_ci(values: list[float], repetitions: int = 1000, seed: int = 20260821) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(repetitions):
        means.append(mean(values[rng.randrange(len(values))] for _ in values))
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
    records: list[dict[str, object]],
    distance_max: float | None = None,
    agreement_min: float = 0.0,
    split: str = "all",
    with_bootstrap: bool = False,
) -> dict[str, object] | None:
    values: list[float] = []
    for record in records:
        if split != "all" and record["split"] != split:
            continue
        if distance_max is not None and float(record["median_distance"]) > distance_max:
            continue
        if float(record["agreement"]) < agreement_min:
            continue
        values.append(float(record["outcome_pips"]))
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
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows, quality = _execution_valid_rows(rows, pair)
    bid, ask = _market_bars(rows)
    bars = empirical._merge(bid, ask)
    horizons = empirical.DEFAULT_HORIZONS
    if len(bars) < empirical.STATE_LOOKBACK + history_states + max(horizons) + 10:
        raise ValueError(f"insufficient bars for {pair}")

    states = [
        state_from_bar_window(bars, index, empirical.STATE_LOOKBACK)
        for index in range(empirical.STATE_LOOKBACK, len(bars))
    ]
    state_index = {state.timestamp: index + empirical.STATE_LOOKBACK for index, state in enumerate(states)}
    targets: list[dict[str, object]] = []

    for position in range(history_states, len(states), sample_stride):
        target = states[position]
        target_index = state_index[target.timestamp]
        if target_index + max(horizons) >= len(bars):
            continue
        history = states[position - history_states : position]
        scaler = fit_scaler(history, DEFAULT_FEATURES)
        nearest = nearest_states(target, history, scaler, k=min(100, len(history)))
        neighbors: list[tuple[object, float]] = []
        for state, distance in nearest:
            state_index_value = state_index[state.timestamp]
            if any(state_index_value + horizon > target_index for horizon in horizons):
                continue
            neighbors.append((state, distance))
        if not neighbors:
            continue

        direction = "long" if float(target.features.get("momentum") or 0.0) >= 0.0 else "short"
        regime = classify_regime(
            float(target.features.get("trend") or 0.0),
            float(target.features.get("trend_strength") or 0.0),
            empirical._volatility_z(target, history),
            int(target.features.get("breakout") or 0),
        )
        distances = [distance for _, distance in neighbors]

        for horizon in horizons:
            evidence: list[float] = []
            for neighbor, _distance in neighbors:
                outcome = future_outcome(bars, state_index[neighbor.timestamp], horizon, direction)
                evidence.append(net_move(outcome.movement, costs))
            if not evidence:
                continue
            target_outcome = future_outcome(bars, target_index, horizon, direction)
            targets.append(
                {
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
                    "outcome_pips": net_move(target_outcome.movement, costs) / PAIR_PIP[pair],
                }
            )

    timestamps = sorted({datetime.fromisoformat(str(record["timestamp"])) for record in targets})
    cutoff = timestamps[int(len(timestamps) * 0.70)] if timestamps else None
    for record in targets:
        record["split"] = "discovery" if cutoff and datetime.fromisoformat(str(record["timestamp"])) < cutoff else "confirmation"
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
    all_records: list[dict[str, object]] = []
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

    # Candidate selection is performed only on the chronological discovery segment.
    candidates: list[dict[str, object]] = []
    regimes = (
        "regime:high_volatility_range",
        "regime:low_volatility_range",
        "regime:trend",
        "regime:high_volatility_trend",
    )
    pairsets = ("all", "JPY")
    for horizon in empirical.DEFAULT_HORIZONS:
        for agreement_min in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
            for distance_max in (None, 0.5, 1.0, 1.5, 2.0):
                for regime in regimes:
                    for pairset in pairsets:
                        subset = [
                            record
                            for record in all_records
                            if record["horizon"] == horizon
                            and record["split"] == "discovery"
                            and record["regime"] == regime
                            and (pairset == "all" or str(record["pair"]).endswith("/JPY"))
                        ]
                        result = evaluate(subset, distance_max, agreement_min, "discovery")
                        if result is not None and int(result["n"]) >= 100:
                            candidates.append(
                                {
                                    "horizon": horizon,
                                    "agreement_min": agreement_min,
                                    "distance_max": distance_max,
                                    "regime": regime,
                                    "pairset": pairset,
                                    "discovery": result,
                                }
                            )

    candidates.sort(
        key=lambda candidate: (
            float(candidate["discovery"]["expectancy_pips"]),
            float(candidate["discovery"]["profit_factor"] or -math.inf),
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
            and (finalist["pairset"] == "all" or str(record["pair"]).endswith("/JPY"))
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
            "candidate_search": "finite threshold grid selected only on discovery data, then frozen",
            "analogue_k": 100,
            "leakage_rule": "an analogue's complete future outcome must end no later than the target timestamp",
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
