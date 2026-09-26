from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from math import inf
from pathlib import Path
from statistics import mean
from typing import Any, TypedDict

from . import sequential_empirical as empirical
from .datafeed_empirical import PAIR_TO_SYMBOL, _execution_valid_rows, _market_bars, load_feed_bars
from .execution import ExecutionAssumptions, net_move
from .multiple_testing import holm_bonferroni
from .non_live_evaluation import block_bootstrap_means, bootstrap_means, profit_factor
from .outcomes import future_outcome
from .statistics import hac_mean_pvalue

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

LOOKBACKS = (12, 24, 48, 96)
BREAKOUT_BUFFERS_ATR = (0.0, 0.25, 0.50)
HORIZONS = (1, 2, 3, 6)
EXPECTED_BAR_INTERVAL = timedelta(minutes=10)
DISCOVERY_FRACTION = 0.60

MIN_DISCOVERY_SAMPLES = 150
MIN_DISCOVERY_PF = 1.10
MIN_POSITIVE_PAIRS = 3
MIN_PAIR_SAMPLES = 20
MAX_PAIR_OBSERVATION_SHARE = 0.80
BOOTSTRAP_REPS = 2000
BOOTSTRAP_BLOCK_SIZE = 5
HOLM_ALPHA = 0.05

SOURCE_RUN_ID = 34139659497
SOURCE_ARTIFACT_NAME = "v5-prepared-nine-pair-feeds"
CONTRACT_VERSION = "v1-breakout-familywise-horizon-purged"


class Candidate(TypedDict):
    lookback: int
    buffer_atr: float
    horizon: int


class Observation(TypedDict):
    timestamp: str
    pair: str
    outcome_pips: float
    split: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_contiguous_window(bars: list[Any], start: int, end: int) -> bool:
    if start < 0 or end >= len(bars) or start > end:
        return False
    return all(
        (current.timestamp - previous.timestamp) == EXPECTED_BAR_INTERVAL
        for previous, current in zip(bars[start:end], bars[start + 1 : end + 1], strict=True)
    )


def _true_range(bar: Any) -> float:
    return max(bar.bid_high, bar.ask_high) - min(bar.bid_low, bar.ask_low)


def _candidate_key(candidate: Candidate) -> str:
    return (
        f"lb={candidate['lookback']}:"
        f"b={candidate['buffer_atr']:.2f}:"
        f"h={candidate['horizon']}"
    )


def _all_candidates() -> list[Candidate]:
    return [
        {"lookback": lookback, "buffer_atr": buffer, "horizon": horizon}
        for lookback in LOOKBACKS
        for buffer in BREAKOUT_BUFFERS_ATR
        for horizon in HORIZONS
    ]


def _split(timestamp: datetime, horizon: int, cutoff: datetime) -> str:
    if timestamp >= cutoff:
        return "confirmation"
    target_end = timestamp + horizon * EXPECTED_BAR_INTERVAL
    return "discovery" if target_end < cutoff else "purged_boundary"


def _max_drawdown(values: list[float]) -> float:
    balance = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        balance += value
        peak = max(peak, balance)
        worst = min(worst, balance - peak)
    return abs(worst)


def _stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "expectancy_pips": mean(values) if values else None,
        "profit_factor": profit_factor(values),
        "win_rate": (sum(value > 0.0 for value in values) / len(values)) if values else None,
        "max_drawdown_pips": _max_drawdown(values),
    }


def _bootstrap(values: list[float], seed: int) -> dict[str, float]:
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=seed)
    block = block_bootstrap_means(
        values,
        block_size=min(BOOTSTRAP_BLOCK_SIZE, len(values)),
        reps=BOOTSTRAP_REPS,
        seed=seed + 1,
    )
    return {
        "ordinary_lower_95_mean": ordinary[49],
        "ordinary_upper_95_mean": ordinary[-50],
        "block_lower_95_mean": block[49],
        "block_upper_95_mean": block[-50],
        "ordinary_probability_positive_mean": mean(value > 0.0 for value in ordinary),
    }


def _pair_robust(
    observations: list[Observation],
) -> tuple[bool, dict[str, dict[str, float | int | None]], float]:
    grouped: dict[str, list[float]] = {}
    for observation in observations:
        grouped.setdefault(observation["pair"], []).append(observation["outcome_pips"])

    breakdown = {
        pair: _stats(values) for pair, values in sorted(grouped.items())
    }
    eligible = {
        pair: result
        for pair, result in breakdown.items()
        if int(result["n"] or 0) >= MIN_PAIR_SAMPLES
    }
    positive = {
        pair: result
        for pair, result in eligible.items()
        if result["expectancy_pips"] is not None
        and result["expectancy_pips"] > 0.0
        and (result["profit_factor"] is None or result["profit_factor"] > 1.0)
    }
    largest_share = max(
        (
            int(result["n"] or 0) / len(observations)
            for result in breakdown.values()
        ),
        default=1.0,
    )
    robust = (
        len(positive) >= MIN_POSITIVE_PAIRS
        and largest_share <= MAX_PAIR_OBSERVATION_SHARE
    )
    return robust, breakdown, largest_share


def _evaluate(
    observations: list[Observation],
    seed: int,
) -> dict[str, Any]:
    ordered = sorted(
        observations, key=lambda item: (item["timestamp"], item["pair"])
    )
    values = [item["outcome_pips"] for item in ordered]
    stats = _stats(values)
    p_value = hac_mean_pvalue(values) if len(values) >= 2 else 1.0
    bootstrap = _bootstrap(values, seed) if len(values) >= 2 else None
    pair_robust, pair_breakdown, largest_share = _pair_robust(ordered)

    return {
        "statistics": stats,
        "raw_hac_one_sided_pvalue": p_value,
        "pair_robust": pair_robust,
        "pair_breakdown": pair_breakdown,
        "largest_pair_observation_share": largest_share,
        "bootstrap": bootstrap,
    }


def _load_bars(
    input_dir: Path,
) -> tuple[dict[str, list[Any]], dict[str, Any], datetime]:
    bars_by_pair: dict[str, list[Any]] = {}
    quality: dict[str, Any] = {}
    eligible_timestamps: set[datetime] = set()

    for pair in PAIR_TO_SYMBOL:
        path = input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"missing verified feed for {pair}: {path}")

        rows, pair_quality = _execution_valid_rows(load_feed_bars(path), pair)
        bid, ask = _market_bars(rows)
        bars = empirical._merge(bid, ask)

        minimum = max(LOOKBACKS) + max(HORIZONS) + 2
        if len(bars) < minimum:
            raise ValueError(f"insufficient bars for {pair}: {len(bars)}")

        bars_by_pair[pair] = bars
        quality[pair] = pair_quality

        for index in range(max(LOOKBACKS), len(bars) - max(HORIZONS)):
            if _is_contiguous_window(
                bars,
                index - max(LOOKBACKS),
                index + max(HORIZONS),
            ):
                eligible_timestamps.add(bars[index].timestamp)

    ordered = sorted(eligible_timestamps)
    if len(ordered) < 200:
        raise ValueError("insufficient global eligible timestamps")

    cutoff = ordered[int(len(ordered) * DISCOVERY_FRACTION)]
    return bars_by_pair, quality, cutoff


def rebuild_observations(
    input_dir: Path,
    sample_stride: int,
) -> tuple[dict[str, list[Observation]], dict[str, Any], datetime, dict[str, Any]]:
    if sample_stride <= 0:
        raise ValueError("sample_stride must be positive")

    bars_by_pair, quality, cutoff = _load_bars(input_dir)
    candidates = _all_candidates()
    observations: dict[str, list[Observation]] = {
        _candidate_key(candidate): [] for candidate in candidates
    }
    costs = ExecutionAssumptions()

    for pair, bars in bars_by_pair.items():
        for lookback in LOOKBACKS:
            for index in range(
                lookback,
                len(bars) - max(HORIZONS),
                sample_stride,
            ):
                if not _is_contiguous_window(
                    bars,
                    index - lookback,
                    index + max(HORIZONS),
                ):
                    continue

                prior = bars[index - lookback : index]
                atr = mean(_true_range(bar) for bar in prior)
                if atr <= 0.0:
                    continue

                prior_high = max(bar.bid_high for bar in prior)
                prior_low = min(bar.ask_low for bar in prior)
                target_timestamp = bars[index].timestamp

                for buffer in BREAKOUT_BUFFERS_ATR:
                    long_signal = (
                        bars[index].ask_close > prior_high + buffer * atr
                    )
                    short_signal = (
                        bars[index].bid_close < prior_low - buffer * atr
                    )
                    if long_signal == short_signal:
                        continue

                    direction = "long" if long_signal else "short"
                    for horizon in HORIZONS:
                        if not _is_contiguous_window(
                            bars, index, index + horizon
                        ):
                            continue

                        split = _split(target_timestamp, horizon, cutoff)
                        if split == "purged_boundary":
                            continue

                        outcome = future_outcome(bars, index, horizon, direction)
                        outcome_pips = (
                            net_move(outcome.return_abs, costs) / PAIR_PIP[pair]
                        )
                        candidate: Candidate = {
                            "lookback": lookback,
                            "buffer_atr": buffer,
                            "horizon": horizon,
                        }
                        observations[_candidate_key(candidate)].append(
                            {
                                "timestamp": target_timestamp.isoformat(),
                                "pair": pair,
                                "outcome_pips": outcome_pips,
                                "split": split,
                            }
                        )

    manifest = {
        pair: {
            "sha256": _sha256_file(
                input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"
            )
        }
        for pair in PAIR_TO_SYMBOL
    }
    return observations, quality, cutoff, manifest


def _candidate_summary(
    candidate: Candidate,
    result: dict[str, Any],
    adjusted_pvalue: float,
) -> dict[str, Any]:
    return {
        "candidate": candidate,
        **result,
        "discovery_hac_holm_adjusted_pvalue": adjusted_pvalue,
        "discovery_family_size": len(_all_candidates()),
    }


def _discovery_passes(
    result: dict[str, Any],
    adjusted_pvalue: float,
) -> bool:
    statistics = result["statistics"]
    bootstrap = result["bootstrap"]
    return (
        int(statistics["n"] or 0) >= MIN_DISCOVERY_SAMPLES
        and result["pair_robust"]
        and statistics["profit_factor"] is not None
        and float(statistics["profit_factor"]) >= MIN_DISCOVERY_PF
        and adjusted_pvalue <= HOLM_ALPHA
        and bootstrap is not None
        and bootstrap["ordinary_lower_95_mean"] > 0.0
        and bootstrap["block_lower_95_mean"] > 0.0
    )


def _failure_reason(
    result: dict[str, Any],
    adjusted_pvalue: float,
) -> str:
    statistics = result["statistics"]
    if int(statistics["n"] or 0) < MIN_DISCOVERY_SAMPLES:
        return "insufficient discovery samples"
    if not result["pair_robust"]:
        return "failed pair-diversity/concentration gate"
    if (
        statistics["profit_factor"] is None
        or float(statistics["profit_factor"]) < MIN_DISCOVERY_PF
    ):
        return "failed discovery profit-factor gate"
    if adjusted_pvalue > HOLM_ALPHA:
        return "failed family-wise HAC gate"
    return "failed ordinary/block bootstrap gate"


def run_discovery(
    input_dir: Path,
    sample_stride: int = 60,
) -> dict[str, Any]:
    observations, quality, cutoff, manifest = rebuild_observations(
        input_dir, sample_stride
    )
    family: list[dict[str, Any]] = []

    for candidate in _all_candidates():
        key = _candidate_key(candidate)
        discovery = [
            observation
            for observation in observations[key]
            if observation["split"] == "discovery"
        ]
        result = _evaluate(
            discovery,
            2026092600 + candidate["lookback"] * 10 + candidate["horizon"],
        )
        family.append({"candidate": candidate, **result})

    adjusted = holm_bonferroni(
        [
            item["raw_hac_one_sided_pvalue"]
            if int(item["statistics"]["n"] or 0) >= MIN_DISCOVERY_SAMPLES
            else 1.0
            for item in family
        ]
    )

    accepted: list[dict[str, Any]] = []
    near_misses: list[dict[str, Any]] = []

    for item, adjusted_pvalue in zip(family, adjusted, strict=True):
        summary = _candidate_summary(
            item["candidate"], item, adjusted_pvalue
        )
        if _discovery_passes(item, adjusted_pvalue):
            accepted.append(summary)
        else:
            near = dict(summary)
            near["near_miss_reason"] = _failure_reason(item, adjusted_pvalue)
            near_misses.append(near)

    accepted.sort(
        key=lambda item: (
            float(item["statistics"]["expectancy_pips"] or -inf),
            float(item["statistics"]["profit_factor"] or -inf),
        ),
        reverse=True,
    )

    confirmation_candidates = accepted[:10]
    confirmation_family: list[dict[str, Any]] = []

    for item in confirmation_candidates:
        candidate = item["candidate"]
        key = _candidate_key(candidate)
        confirmation = [
            observation
            for observation in observations[key]
            if observation["split"] == "confirmation"
        ]
        result = _evaluate(
            confirmation,
            2026092699 + candidate["lookback"] * 10 + candidate["horizon"],
        )
        raw_values = [
            observation["outcome_pips"] for observation in confirmation
        ]
        result["cost_stress_0_5_pip"] = _stats(
            [value - 0.5 for value in raw_values]
        )
        result["cost_stress_1_0_pip"] = _stats(
            [value - 1.0 for value in raw_values]
        )
        confirmation_family.append({"candidate": candidate, **result})

    confirmation_adjusted = (
        holm_bonferroni(
            [item["raw_hac_one_sided_pvalue"] for item in confirmation_family]
        )
        if confirmation_family
        else []
    )

    confirmation_results: list[dict[str, Any]] = []
    for item, adjusted_pvalue in zip(
        confirmation_family, confirmation_adjusted, strict=True
    ):
        statistics = item["statistics"]
        bootstrap = item["bootstrap"]
        stress_expectancy = item["cost_stress_0_5_pip"]["expectancy_pips"]
        confirmation_pass = (
            int(statistics["n"] or 0) >= 100
            and item["pair_robust"]
            and statistics["profit_factor"] is not None
            and float(statistics["profit_factor"]) >= MIN_DISCOVERY_PF
            and adjusted_pvalue <= HOLM_ALPHA
            and bootstrap is not None
            and bootstrap["ordinary_lower_95_mean"] > 0.0
            and bootstrap["block_lower_95_mean"] > 0.0
            and stress_expectancy is not None
            and float(stress_expectancy) > 0.0
        )
        output = dict(item)
        output["confirmation_hac_holm_adjusted_pvalue"] = adjusted_pvalue
        output["confirmation_pass"] = confirmation_pass
        output["live_execution_authorized"] = False
        confirmation_results.append(output)

    return {
        "status": "BREAKOUT_FAMILY_DISCOVERY_COMPLETED",
        "contract_version": CONTRACT_VERSION,
        "candidate_count": len(accepted),
        "accepted_candidates": accepted,
        "near_misses": near_misses[:25],
        "confirmation_results": confirmation_results,
        "confirmation_candidate_count": len(confirmation_candidates),
        "family_size": len(_all_candidates()),
        "cutoff": cutoff.isoformat(),
        "record_count_by_candidate": {
            key: len(value) for key, value in observations.items()
        },
        "source_manifest": manifest,
        "data_quality": quality,
        "selection_policy": {
            "direction": (
                "ASK-close breakout above prior BID high for long; "
                "BID-close breakout below prior ASK low for short"
            ),
            "lookbacks": list(LOOKBACKS),
            "buffers_atr": list(BREAKOUT_BUFFERS_ATR),
            "horizons": list(HORIZONS),
            "split": "global chronological 60/40 split with horizon purge",
            "minimum_discovery_samples": MIN_DISCOVERY_SAMPLES,
            "minimum_discovery_profit_factor": MIN_DISCOVERY_PF,
            "minimum_positive_pairs": MIN_POSITIVE_PAIRS,
            "minimum_pair_samples": MIN_PAIR_SAMPLES,
            "maximum_pair_observation_share": MAX_PAIR_OBSERVATION_SHARE,
            "familywise_control": (
                "one-sided HAC mean p-values across the full 48-hypothesis "
                "family followed by Holm correction"
            ),
            "bootstrap_gate": (
                "ordinary and block lower 95% mean both greater than zero"
            ),
            "confirmation_gate": (
                "frozen discovery finalists only; Holm-adjusted confirmation "
                "HAC, bootstrap lower tails, pair robustness, and 0.5-pip "
                "stress must all remain positive"
            ),
            "extra_slippage_commission_pips_for_selection": 0.0,
            "live_execution_authorized": False,
        },
        "orchestration_binding": {
            "source_run_id": SOURCE_RUN_ID,
            "source_artifact_name": SOURCE_ARTIFACT_NAME,
        },
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Non-live breakout family research on verified nine-pair BID/ASK feeds."
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    args = parser.parse_args()
    result = run_discovery(Path(args.input_dir), args.sample_stride)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"BREAKOUT_DISCOVERY_STATE={result['status']}")
    print(f"CANDIDATE_COUNT={result['candidate_count']}")
    print(
        "CONFIRMATION_CANDIDATE_COUNT="
        f"{result['confirmation_candidate_count']}"
    )
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
