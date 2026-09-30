from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

import numpy as np

import research.currency_strength_discovery as discovery
from research.non_live_evaluation import bootstrap_means
from research.statistics import hac_mean_pvalue


CONFIRMATION_CONTRACT_VERSION = "v1-currency-strength-confirmation"
MIN_CONFIRMATION_TRADES = 150
MIN_CONFIRMATION_TIMESTAMP_OBS = 100
MIN_CONFIRMATION_PAIR_TRADES = 20
MIN_CONFIRMATION_POSITIVE_PAIRS = 3
MAX_CONFIRMATION_PAIR_CONCENTRATION = 0.80
BOOTSTRAP_REPS = 2000
BOOTSTRAP_BLOCK_SIZE = 6
BOOTSTRAP_LOWER_INDEX = 49
STRESS_COSTS_PIPS = (0.5, 1.0, 1.5)


def _bootstrap_block_lower(
    timestamp_means: Mapping[int, float],
    reps: int,
    seed: int,
) -> float:
    if len(timestamp_means) < 2:
        return math.nan
    ordered = sorted(timestamp_means)
    blocks = [
        ordered[index : index + BOOTSTRAP_BLOCK_SIZE]
        for index in range(0, len(ordered), BOOTSTRAP_BLOCK_SIZE)
    ]
    rng = np.random.default_rng(seed)
    means: list[float] = []
    sample_size = len(ordered)
    for _ in range(reps):
        sampled: list[int] = []
        while len(sampled) < sample_size:
            sampled.extend(blocks[int(rng.integers(0, len(blocks)))])
        means.append(mean(timestamp_means[timestamp] for timestamp in sampled[:sample_size]))
    return float(np.quantile(np.asarray(means), 0.025))


def _confirmation_positions(
    feeds: Mapping[str, discovery.Feed],
    cutoff_ms: int,
) -> tuple[dict[str, list[int]], list[int]]:
    common_timestamps = sorted(
        set.intersection(*(set(feed.timestamps) for feed in feeds.values()))
    )
    confirmation_timestamps: list[int] = []
    for timestamp_ms in common_timestamps:
        if timestamp_ms < cutoff_ms:
            continue
        eligible = True
        for feed in feeds.values():
            position = feed.timestamp_index[timestamp_ms]
            end_position = position + max(discovery.HORIZONS)
            if position < max(discovery.LOOKBACKS) or end_position >= len(feed.timestamps):
                eligible = False
                break
            if not math.isfinite(float(feed.rolling_vol[position])):
                eligible = False
                break
            if not discovery._contiguous(
                feed.timestamps,
                position - max(discovery.LOOKBACKS),
                end_position,
            ):
                eligible = False
                break
        if eligible:
            confirmation_timestamps.append(timestamp_ms)

    positions = {
        pair: [feeds[pair].timestamp_index[ts] for ts in confirmation_timestamps]
        for pair in feeds
    }
    return positions, confirmation_timestamps


def _candidate_values(
    feeds: Mapping[str, discovery.Feed],
    positions: Mapping[str, list[int]],
    signals: Mapping[tuple[int, int, str, str], float],
    candidate: Mapping[str, Any],
    cutoff_ms: int,
) -> tuple[list[float], dict[str, list[float]], dict[int, list[float]]]:
    lookback = int(candidate["lookback"])
    horizon = int(candidate["horizon"])
    mode = str(candidate["mode"])
    orientation = str(candidate["orientation"])
    threshold = float(candidate["threshold"])

    values: list[float] = []
    by_pair: dict[str, list[float]] = defaultdict(list)
    by_timestamp: dict[int, list[float]] = defaultdict(list)

    for pair, pair_positions in positions.items():
        feed = feeds[pair]
        for position in pair_positions:
            timestamp_ms = int(feed.timestamps[position])
            if timestamp_ms < cutoff_ms:
                continue
            signal = signals.get((timestamp_ms, lookback, pair, mode))
            if signal is None or not math.isfinite(signal) or abs(signal) < threshold:
                continue

            entry_position = position + discovery.ENTRY_DELAY_BARS
            end_position = position + horizon
            if end_position >= len(feed.timestamps):
                continue
            if not discovery._contiguous(feed.timestamps, position, end_position):
                continue

            direction = 1 if signal > 0 else -1
            if orientation == "reversion":
                direction *= -1

            if direction > 0:
                outcome = (
                    feed.bid_close[end_position] - feed.ask_open[entry_position]
                ) / discovery.PAIR_PIP[pair]
            else:
                outcome = (
                    feed.bid_open[entry_position] - feed.ask_close[end_position]
                ) / discovery.PAIR_PIP[pair]

            value = float(outcome) - discovery.DISCOVERY_COST_PIPS
            values.append(value)
            by_pair[pair].append(value)
            by_timestamp.setdefault(timestamp_ms, []).append(value)

    return values, by_pair, by_timestamp


def evaluate_candidate(
    feeds: Mapping[str, discovery.Feed],
    candidate: Mapping[str, Any],
    cutoff_ms: int,
    confirmation_timestamps: list[int],
) -> dict[str, Any]:
    positions = {
        pair: [feeds[pair].timestamp_index[ts] for ts in confirmation_timestamps]
        for pair in feeds
    }
    signals = discovery.build_signal_index(feeds, confirmation_timestamps)
    values, by_pair, by_timestamp = _candidate_values(
        feeds, positions, signals, candidate, cutoff_ms
    )

    if not values:
        return {
            "n": 0,
            "unique_timestamps": 0,
            "expectancy_pips": None,
            "profit_factor": None,
            "hac_one_sided_pvalue": 1.0,
            "ordinary_bootstrap_lower": math.nan,
            "cluster_block_bootstrap_lower": math.nan,
            "positive_pair_count": 0,
            "largest_pair_observation_share": 1.0,
            "stress": {},
            "gates": {},
            "state": "INCOMPLETE",
            "inference_unit": "per-timestamp cross-sectional mean outcome",
        }

    timestamp_means = {
        timestamp: mean(items) for timestamp, items in sorted(by_timestamp.items())
    }
    ordinary = bootstrap_means(
        list(timestamp_means.values()), reps=BOOTSTRAP_REPS, seed=20260923
    )
    cluster_lower = _bootstrap_block_lower(
        timestamp_means, reps=BOOTSTRAP_REPS, seed=20260924
    )

    positive_pairs = sum(
        1
        for pair_values in by_pair.values()
        if len(pair_values) >= MIN_CONFIRMATION_PAIR_TRADES
        and mean(pair_values) > 0
        and (
            (pair_pf := discovery.profit_factor(pair_values)) is not None
            and float(pair_pf) > 1.0
        )
    )
    concentration = max(
        (len(pair_values) / len(values) for pair_values in by_pair.values()),
        default=1.0,
    )
    expectancy = mean(values)
    pf_value = discovery.profit_factor(values)
    stress = {
        str(cost): {
            "expectancy_pips": mean(value - cost for value in values),
            "profit_factor": discovery.profit_factor([value - cost for value in values]),
        }
        for cost in STRESS_COSTS_PIPS
    }

    gates = {
        "minimum_confirmation_trades": len(values) >= MIN_CONFIRMATION_TRADES,
        "minimum_confirmation_timestamps": len(timestamp_means) >= MIN_CONFIRMATION_TIMESTAMP_OBS,
        "positive_expectancy": expectancy > 0,
        "profit_factor_gte_1_10": pf_value is not None and float(pf_value) >= 1.10,
        "ordinary_cluster_bootstrap_lower_gt_0": float(ordinary[BOOTSTRAP_LOWER_INDEX]) > 0,
        "blocked_timestamp_bootstrap_lower_gt_0": cluster_lower > 0,
        "positive_pair_count_min_3_and_min_20_each": positive_pairs >= MIN_CONFIRMATION_POSITIVE_PAIRS,
        "pair_observation_concentration_lte_80pct": concentration <= MAX_CONFIRMATION_PAIR_CONCENTRATION,
    }

    return {
        "n": len(values),
        "unique_timestamps": len(timestamp_means),
        "expectancy_pips": expectancy,
        "profit_factor": pf_value,
        "hac_one_sided_pvalue": hac_mean_pvalue(list(timestamp_means.values())),
        "ordinary_bootstrap_lower": float(ordinary[BOOTSTRAP_LOWER_INDEX]),
        "cluster_block_bootstrap_lower": cluster_lower,
        "positive_pair_count": positive_pairs,
        "largest_pair_observation_share": concentration,
        "stress": stress,
        "gates": gates,
        "state": "PASS" if all(gates.values()) else "FAIL",
        "inference_unit": "per-timestamp cross-sectional mean outcome",
    }


def run_confirmation(input_dir: Path, discovery_report_path: Path) -> dict[str, Any]:
    report = json.loads(discovery_report_path.read_text(encoding="utf-8"))
    if report.get("status") != "CURRENCY_STRENGTH_DISCOVERY_COMPLETED":
        raise ValueError("discovery report is not a completed currency-strength discovery")
    if report.get("contract_version") != "v4-currency-strength-familywise-next-open-signal-horizon-leave-one-pair-out":
        raise ValueError("discovery report contract version is not the frozen v3 family")
    if report.get("discovery_family_size") != 144:
        raise ValueError("discovery family size is not 144")
    if report.get("candidate_count", 0) < 1:
        raise ValueError("no familywise discovery candidate exists")
    if report.get("selection_policy", {}).get("confirmation_used_for_selection") is not False:
        raise ValueError("confirmation data was marked as used for discovery selection")
    if report.get("live_execution_authorized") is not False or report.get("promotion_authorized") is not False:
        raise ValueError("discovery report authorization boundary is not fail-closed")

    frozen = report["top_candidates"][0]
    candidate = frozen["candidate"]
    fingerprint = str(frozen["candidate_fingerprint"])
    if fingerprint != discovery.candidate_fingerprint(candidate):
        raise ValueError("frozen rank-1 candidate fingerprint mismatch")

    cutoff_ms = int(
        datetime.fromisoformat(
            str(report["global_split_cutoff"]).replace("Z", "+00:00")
        ).timestamp()
        * 1000
    )

    feeds, manifest = discovery.load_feeds(input_dir)
    expected_manifest = report["source_manifest"]
    for pair in discovery.PAIR_CURRENCY:
        for key in ("sha256", "valid_rows"):
            if manifest[pair].get(key) != expected_manifest[pair].get(key):
                raise ValueError(f"source artifact changed for {pair}: {key}")

    _, confirmation_timestamps = _confirmation_positions(feeds, cutoff_ms)
    result = evaluate_candidate(feeds, candidate, cutoff_ms, confirmation_timestamps)

    return {
        "status": "CURRENCY_STRENGTH_CONFIRMATION_COMPLETED",
        "contract_version": CONFIRMATION_CONTRACT_VERSION,
        "discovery_contract_version": discovery.CONTRACT_VERSION,
        "candidate": {
            "rank": 1,
            "candidate": candidate,
            "candidate_fingerprint": fingerprint,
        },
        "candidate_selection_rule": "rank-1 familywise discovery candidate was frozen before confirmation; confirmation cannot select a fallback candidate",
        "global_split_cutoff": report["global_split_cutoff"],
        "confirmation": result,
        "source_manifest": manifest,
        "confirmation_timestamp_count": len(confirmation_timestamps),
        "promotion_authorized": False,
        "live_execution_authorized": False,
        "market_data_accessed": True,
        "orchestration_binding": report.get("orchestration_binding", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Untouched non-live confirmation of the frozen rank-1 currency-strength discovery candidate."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--discovery-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = run_confirmation(Path(args.input_dir), Path(args.discovery_report))
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"STATE={result['confirmation']['state']}")
    print(f"CONFIRMATION_N={result['confirmation']['n']}")
    print(f"CONFIRMATION_EXPECTANCY_PIPS={result['confirmation']['expectancy_pips']}")
    print(f"CONFIRMATION_PROFIT_FACTOR={result['confirmation']['profit_factor']}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
