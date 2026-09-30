from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import xml.etree.ElementTree as ET
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from math import inf
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping, TypedDict, cast

import httpx

from . import sequential_empirical as empirical
from .datafeed_empirical import PAIR_TO_SYMBOL, _execution_valid_rows, _market_bars, load_feed_bars
from .execution import ExecutionAssumptions, net_move
from .multiple_testing import holm_bonferroni
from .non_live_evaluation import block_bootstrap_means, bootstrap_means, profit_factor
from .outcomes import future_outcome
from .pipeline import state_from_bar_window
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
PAIR_CURRENCIES = {
    "EUR/USD": ("EUR", "USD"), "GBP/USD": ("GBP", "USD"),
    "USD/JPY": ("USD", "JPY"), "AUD/USD": ("AUD", "USD"),
    "USD/CAD": ("USD", "CAD"), "USD/CHF": ("USD", "CHF"),
    "NZD/USD": ("NZD", "USD"), "EUR/JPY": ("EUR", "JPY"),
    "GBP/JPY": ("GBP", "JPY"),
}
BIS_CODES = {"USD": "US", "EUR": "XM", "GBP": "GB", "JPY": "JP",
             "AUD": "AU", "NZD": "NZ", "CAD": "CA", "CHF": "CH"}
BIS_BASE_URL = "https://stats.bis.org/api/v1/data/WS_CBPOL"
EXPECTED_BAR_INTERVAL = timedelta(minutes=10)
STATE_LOOKBACK = 20
HORIZONS = (6, 36, 144)
CARRY_THRESHOLDS = (0.25, 0.50, 1.00, 2.00)
TREND_STRENGTH_MIN = (0.00, 0.25, 0.50)
VOLATILITY_STATES = ("any", "high", "normal", "low")
MIN_DISCOVERY_SAMPLES = 150
MIN_DISCOVERY_PF = 1.10
MIN_DISCOVERY_BOOTSTRAP_LOWER = 0.0
MIN_POSITIVE_PAIRS = 3
MIN_PAIR_SAMPLES = 20
MAX_PAIR_OBSERVATION_SHARE = 0.80
BOOTSTRAP_REPS = 2000
BOOTSTRAP_BLOCK_SIZE = 5
HOLM_ALPHA = 0.05
CONTRACT_VERSION = "v1-carry-factor-bis-daily-strict-prior"

class Candidate(TypedDict):
    horizon: int
    carry_threshold_pp: float
    trend_strength_min: float
    volatility_state: str



def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_sdmx_series(raw: bytes) -> list[tuple[date, float]]:
    root = ET.fromstring(raw)
    series_nodes = [n for n in root.iter() if _local(n.tag) == "Series"]
    candidates: list[list[tuple[date, float]]] = []
    for series in series_nodes:
        rows: dict[date, float] = {}
        for obs in series.iter():
            if _local(obs.tag) != "Obs":
                continue
            period = obs.attrib.get("TIME_PERIOD")
            value = obs.attrib.get("OBS_VALUE")
            if period is None or value is None:
                for child in obs:
                    name = _local(child.tag)
                    period = period or (child.attrib.get("value") if name == "ObsDimension" else None)
                    value = value or (child.attrib.get("value") if name == "ObsValue" else None)
            if period is None or value is None:
                continue
            try:
                parsed = float(value)
            except ValueError:
                continue
            if not math.isfinite(parsed):
                continue
            rows[date.fromisoformat(period)] = parsed
        if rows:
            candidates.append(sorted(rows.items()))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one BIS policy-rate series, found {len(candidates)}")
    return candidates[0]


def _fetch_rate(
    client: httpx.Client, currency: str, start: date, end: date
) -> tuple[list[tuple[date, float]], dict[str, Any]]:
    url = f"{BIS_BASE_URL}/D.{BIS_CODES[currency]}/all"
    params = {"startPeriod": start.isoformat(), "endPeriod": end.isoformat(), "detail": "full"}
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = client.get(url, params=params, headers={"Accept": "application/xml"})
            response.raise_for_status()
            return _parse_sdmx_series(response.content), {
                "currency": currency,
                "country": BIS_CODES[currency],
                "url": str(response.url),
                "sha256_response": hashlib.sha256(response.content).hexdigest(),
            }
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            last = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"BIS rate fetch failed for {currency}") from last


def _strict_prior_rate(series: list[tuple[date, float]], target_date: date) -> float | None:
    dates = [item[0] for item in series]
    index = bisect_left(dates, target_date) - 1
    return None if index < 0 else series[index][1]


def _carry_diff(
    policy: Mapping[str, list[tuple[date, float]]],
    pair: str,
    ts: datetime,
) -> float | None:
    base, quote = PAIR_CURRENCIES[pair]
    a = _strict_prior_rate(policy[base], ts.date())
    b = _strict_prior_rate(policy[quote], ts.date())
    return None if a is None or b is None else a - b


def _vol_bucket(current: float, history: list[float]) -> str:
    if not history:
        return "normal"
    baseline = median(history)
    if baseline <= 0:
        return "normal"
    ratio = current / baseline
    if ratio >= 1.25:
        return "high"
    if ratio <= 0.80:
        return "low"
    return "normal"


def _contiguous(bars: list[Any], start: int, end: int) -> bool:
    if start < 0 or end >= len(bars):
        return False
    return all(
        b.timestamp - a.timestamp == EXPECTED_BAR_INTERVAL
        for a, b in zip(bars[start:end], bars[start + 1:end + 1], strict=True)
    )


def _grid() -> list[Candidate]:
    return [
        {"horizon": h, "carry_threshold_pp": t, "trend_strength_min": s, "volatility_state": v}
        for h in HORIZONS for t in CARRY_THRESHOLDS
        for s in TREND_STRENGTH_MIN for v in VOLATILITY_STATES
    ]


def _stats(values: list[float]) -> dict[str, Any]:
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return {
        "n": len(values),
        "expectancy_pips": mean(values) if values else None,
        "profit_factor": profit_factor(values),
        "win_rate": mean([v > 0 for v in values]) if values else None,
        "max_drawdown_pips": abs(worst),
    }


def _pair_gate(records: list[dict[str, Any]]) -> tuple[bool, dict[str, Any], float]:
    grouped: dict[str, list[float]] = {}
    for row in records:
        grouped.setdefault(row["pair"], []).append(float(row["outcome_pips"]))
    breakdown = {pair: _stats(values) for pair, values in sorted(grouped.items())}
    positive = [
        result for result in breakdown.values()
        if int(result["n"] or 0) >= MIN_PAIR_SAMPLES
        and result["expectancy_pips"] is not None and result["expectancy_pips"] > 0
        and result["profit_factor"] is not None and result["profit_factor"] > 1
    ]
    concentration = max(
        (int(result["n"]) / len(records) for result in breakdown.values()),
        default=1.0,
    )
    return len(positive) >= MIN_POSITIVE_PAIRS and concentration <= MAX_PAIR_OBSERVATION_SHARE, breakdown, concentration


def _bootstrap(values: list[float], seed: int) -> dict[str, float]:
    ordinary = bootstrap_means(values, reps=BOOTSTRAP_REPS, seed=seed)
    block = block_bootstrap_means(values, block_size=min(BOOTSTRAP_BLOCK_SIZE, len(values)),
                                  reps=BOOTSTRAP_REPS, seed=seed + 1)
    return {
        "ordinary_lower_95_mean": ordinary[49],
        "ordinary_upper_95_mean": ordinary[-50],
        "block_lower_95_mean": block[49],
        "block_upper_95_mean": block[-50],
        "ordinary_probability_positive_mean": mean(v > 0 for v in ordinary),
    }



def _fixed_candidate_filter(records: list[dict[str, Any]], candidate: Candidate, split: str) -> list[dict[str, Any]]:
    return [
        row for row in records
        if row["split"] == split
        and row["horizon"] == candidate["horizon"]
        and abs(float(row["carry_diff_pp"])) >= float(candidate["carry_threshold_pp"])
        and float(row["trend_strength"]) >= float(candidate["trend_strength_min"])
        and (candidate["volatility_state"] == "any" or row["volatility_state"] == candidate["volatility_state"])
    ]


def _confirmation_result(records: list[dict[str, Any]], candidate: Candidate, seed: int) -> dict[str, Any]:
    values = [float(row["outcome_pips"]) for row in records]
    stats = _stats(values)
    pair_robust, pair_breakdown, concentration = _pair_gate(records)
    bootstrap = _bootstrap(values, seed) if len(values) >= MIN_DISCOVERY_SAMPLES else None
    p_value = hac_mean_pvalue(values) if len(values) >= 2 else 1.0
    return {
        "candidate": candidate,
        "statistics": stats,
        "raw_hac_one_sided_pvalue": p_value,
        "pair_robust": pair_robust,
        "pair_breakdown": pair_breakdown,
        "largest_pair_observation_share": concentration,
        "bootstrap": bootstrap,
    }


def run_discovery(
    input_dir: Path,
    sample_stride: int = 6,
    start: date = date(2020, 1, 1),
    end: date | None = None,
) -> dict[str, Any]:
    if sample_stride <= 0:
        raise ValueError("sample_stride must be positive")
    end = end or datetime.now(timezone.utc).date()

    policy: dict[str, list[tuple[date, float]]] = {}
    rate_manifest: dict[str, Any] = {}
    with httpx.Client(timeout=30.0) as client:
        for currency in sorted(BIS_CODES):
            series, manifest = _fetch_rate(client, currency, start, end)
            policy[currency] = series
            rate_manifest[currency] = {
                **manifest,
                "observations": len(series),
                "first_date": series[0][0].isoformat(),
                "last_date": series[-1][0].isoformat(),
            }

    pair_bars: dict[str, list[Any]] = {}
    quality: dict[str, Any] = {}
    all_timestamps: list[datetime] = []
    for pair in PAIR_TO_SYMBOL:
        rows, pair_quality = _execution_valid_rows(
            load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"), pair
        )
        bid, ask = _market_bars(rows)
        bars = empirical._merge(bid, ask)
        pair_bars[pair] = bars
        quality[pair] = pair_quality
        for index in range(STATE_LOOKBACK, len(bars) - max(HORIZONS)):
            if _contiguous(bars, index - STATE_LOOKBACK, index + max(HORIZONS)):
                all_timestamps.append(bars[index].timestamp)

    if len(all_timestamps) < 200:
        raise ValueError("insufficient timestamps for chronological split")
    cutoff = sorted(all_timestamps)[int(0.60 * len(all_timestamps))]

    all_records: list[dict[str, Any]] = []
    costs = ExecutionAssumptions()
    for pair, bars in pair_bars.items():
        states: dict[int, Any] = {}
        volatility: dict[int, float] = {}
        for index in range(STATE_LOOKBACK, len(bars)):
            if not _contiguous(bars, index - STATE_LOOKBACK, index):
                continue
            state = state_from_bar_window(bars, index, STATE_LOOKBACK)
            states[index] = state
            volatility[index] = float(cast(float, state.features["volatility"]))
        valid = sorted(states)

        for position in range(0, len(valid), sample_stride):
            index = valid[position]
            state = states[index]
            carry = _carry_diff(policy, pair, state.timestamp)
            if carry is None:
                continue
            prior_vol = [volatility[valid[i]] for i in range(max(0, position - 200), position)]
            bucket = _vol_bucket(volatility[index], prior_vol)
            trend = float(cast(float, state.features["trend_strength"]))

            if abs(carry) < min(CARRY_THRESHOLDS):
                continue

            if state.timestamp < cutoff:
                split = "discovery"
            else:
                split = "confirmation"

            for horizon in HORIZONS:
                end_index = index + horizon
                if end_index >= len(bars) or not _contiguous(bars, index, end_index):
                    continue
                if split == "discovery" and bars[end_index].timestamp >= cutoff:
                    continue

                direction = "long" if carry > 0 else "short"
                outcome = future_outcome(bars, index, horizon, direction)
                all_records.append({
                    "pair": pair,
                    "timestamp": state.timestamp.isoformat(),
                    "horizon": horizon,
                    "carry_diff_pp": carry,
                    "carry_direction": direction,
                    "trend_strength": trend,
                    "volatility_state": bucket,
                    "outcome_pips": net_move(outcome.return_abs, costs) / PAIR_PIP[pair],
                    "split": split,
                })

    family: list[dict[str, Any]] = []
    for candidate in _grid():
        records = [
            row for row in all_records
            if row["split"] == "discovery"
            and row["horizon"] == candidate["horizon"]
            and abs(float(row["carry_diff_pp"])) >= float(candidate["carry_threshold_pp"])
            and float(row["trend_strength"]) >= float(candidate["trend_strength_min"])
            and (candidate["volatility_state"] == "any" or row["volatility_state"] == candidate["volatility_state"])
        ]
        values = [float(row["outcome_pips"]) for row in records]
        robust, pair_breakdown, concentration = _pair_gate(records)
        p_value = hac_mean_pvalue(values) if len(values) >= 2 else 1.0
        item: dict[str, Any] = {
            "candidate": candidate,
            "statistics": _stats(values),
            "raw_hac_one_sided_pvalue": p_value,
            "pair_robust": robust,
            "pair_breakdown": pair_breakdown,
            "largest_pair_observation_share": concentration,
            "bootstrap": None,
        }
        stats = item["statistics"]
        if (int(stats["n"] or 0) >= MIN_DISCOVERY_SAMPLES
                and stats["profit_factor"] is not None
                and float(stats["profit_factor"]) >= MIN_DISCOVERY_PF
                and p_value <= HOLM_ALPHA):
            item["bootstrap"] = _bootstrap(
                values,
                2026092600 + int(candidate["horizon"]) * 100
                + int(float(candidate["carry_threshold_pp"]) * 100),
            )
        family.append(item)

    adjusted = holm_bonferroni([
        float(item["raw_hac_one_sided_pvalue"])
        if int(item["statistics"]["n"] or 0) >= MIN_DISCOVERY_SAMPLES else 1.0
        for item in family
    ])

    candidates: list[dict[str, Any]] = []
    near_misses: list[dict[str, Any]] = []
    for item, adjusted_pvalue in zip(family, adjusted, strict=True):
        stats = item["statistics"]
        bootstrap = item["bootstrap"]
        passed = (
            int(stats["n"] or 0) >= MIN_DISCOVERY_SAMPLES
            and item["pair_robust"]
            and stats["profit_factor"] is not None
            and float(stats["profit_factor"]) >= MIN_DISCOVERY_PF
            and adjusted_pvalue <= HOLM_ALPHA
            and isinstance(bootstrap, dict)
            and float(bootstrap["ordinary_lower_95_mean"]) > MIN_DISCOVERY_BOOTSTRAP_LOWER
            and float(bootstrap["block_lower_95_mean"]) > MIN_DISCOVERY_BOOTSTRAP_LOWER
        )
        summary = {
            "candidate": item["candidate"],
            "statistics": stats,
            "raw_hac_one_sided_pvalue": item["raw_hac_one_sided_pvalue"],
            "holm_adjusted_pvalue": adjusted_pvalue,
            "pair_robust": item["pair_robust"],
            "pair_breakdown": item["pair_breakdown"],
            "largest_pair_observation_share": item["largest_pair_observation_share"],
            "bootstrap": bootstrap,
        }
        if passed:
            candidates.append(summary)
        else:
            near = dict(summary)
            if not item["pair_robust"]:
                reason = "failed discovery pair-diversity/concentration gate"
            elif stats["profit_factor"] is None or float(stats["profit_factor"]) < MIN_DISCOVERY_PF:
                reason = "failed discovery profit-factor gate"
            elif adjusted_pvalue > HOLM_ALPHA:
                reason = "failed discovery-family Holm-adjusted HAC p-value"
            else:
                reason = "failed discovery bootstrap lower-tail gate"
            near["near_miss_reason"] = reason
            near_misses.append(near)

    candidates.sort(
        key=lambda item: (
            float(item["statistics"]["expectancy_pips"] or -inf),
            float(item["statistics"]["profit_factor"] or -inf),
        ),
        reverse=True,
    )

    # Holdout is evaluated only after discovery selection. It never participates
    # in discovery ranking, family construction, or candidate selection.
    confirmation_pvalues: list[float] = []
    confirmation_items: list[dict[str, Any]] = []
    for rank, item in enumerate(candidates):
        candidate = cast(Candidate, item["candidate"])
        confirmation_records = _fixed_candidate_filter(all_records, candidate, "confirmation")
        result = _confirmation_result(confirmation_records, candidate, 2026092700 + rank)
        confirmation_items.append(result)
        confirmation_pvalues.append(float(result["raw_hac_one_sided_pvalue"]) if result["statistics"]["n"] >= 2 else 1.0)

    confirmation_adjusted = holm_bonferroni(confirmation_pvalues)
    confirmed_candidates: list[dict[str, Any]] = []
    for result, adjusted_pvalue in zip(confirmation_items, confirmation_adjusted, strict=True):
        stats = result["statistics"]
        bootstrap = result["bootstrap"]
        confirmed = (
            int(stats["n"] or 0) >= MIN_DISCOVERY_SAMPLES
            and result["pair_robust"]
            and stats["profit_factor"] is not None
            and float(stats["profit_factor"]) >= MIN_DISCOVERY_PF
            and adjusted_pvalue <= HOLM_ALPHA
            and isinstance(bootstrap, dict)
            and float(bootstrap["ordinary_lower_95_mean"]) > MIN_DISCOVERY_BOOTSTRAP_LOWER
            and float(bootstrap["block_lower_95_mean"]) > MIN_DISCOVERY_BOOTSTRAP_LOWER
        )
        result["holm_adjusted_pvalue"] = adjusted_pvalue
        result["confirmed_on_holdout"] = confirmed
        if confirmed:
            confirmed_candidates.append(result)

    for item in candidates:
        matching = next(
            (result for result in confirmation_items if result["candidate"] == item["candidate"]),
            None,
        )
        item["confirmation"] = matching

    return {
        "status": "CARRY_FACTOR_DISCOVERY_COMPLETED",
        "contract_version": CONTRACT_VERSION,
        "family_size": len(_grid()),
        "candidate_count": len(candidates),
        "top_candidates": candidates[:25],
        "holdout_confirmed_candidates": confirmed_candidates[:25],
        "near_misses": near_misses[:25],
        "record_count": len(all_records),
        "global_split_cutoff": cutoff.isoformat(),
        "policy_rate_manifest": rate_manifest,
        "data_quality": quality,
        "selection_policy": {
            "signal": "long base currency when strict-prior-day policy-rate differential >= threshold; short base currency when <= -threshold",
            "rate_source": "BIS central bank policy rates, daily",
            "lookahead_protection": "same-day policy-rate observations are never used",
            "horizons": list(HORIZONS),
            "carry_thresholds_pp": list(CARRY_THRESHOLDS),
            "trend_strength_min": list(TREND_STRENGTH_MIN),
            "volatility_states": list(VOLATILITY_STATES),
            "familywise_control": "one-sided HAC mean p-values for the full 144-hypothesis family followed by Holm correction",
            "bootstrap_gate": "ordinary and block lower 95% mean both > 0",
            "minimum_discovery_samples": MIN_DISCOVERY_SAMPLES,
            "minimum_discovery_profit_factor": MIN_DISCOVERY_PF,
            "minimum_positive_pairs": MIN_POSITIVE_PAIRS,
            "max_pair_observation_share": MAX_PAIR_OBSERVATION_SHARE,
            "confirmation_used_for_selection": False,
            "holdout_evaluated_after_discovery": True,
            "holdout_selection_adjustment": "Holm correction across discovery-selected candidates; holdout results never alter discovery ranking",
        },
        "promotion_authorized": False,
        "live_execution_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Non-live BIS carry-factor discovery on verified nine-pair BID/ASK feeds.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=6)
    parser.add_argument("--start", default="2020-01-01")
    args = parser.parse_args()
    result = run_discovery(
        Path(args.input_dir),
        sample_stride=args.sample_stride,
        start=date.fromisoformat(args.start),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"CARRY_DISCOVERY_STATE={result['status']}")
    print(f"CANDIDATE_COUNT={result['candidate_count']}")
    print("PROMOTION_AUTHORIZED=false")
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
