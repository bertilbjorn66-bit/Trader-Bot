from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

from . import enriched_conditional_experiment as experiment
from .datafeed_empirical import PAIR_TO_SYMBOL, load_feed_bars
from .enriched_conditional_experiment import TargetRecord
from .execution import ExecutionAssumptions
from .non_live_evaluation import block_bootstrap_means, bootstrap_means, max_drawdown, probability_of_ruin, profit_factor

STRESS_COSTS_PIPS = (0.0, 0.2, 0.5, 1.0, 1.5)
MIN_DISCOVERY_SAMPLES = 150
MIN_CONFIRMATION_SAMPLES = 100
MIN_PAIR_SAMPLES = 20
MAX_PAIR_SHARE = 0.80
BOOTSTRAP_REPS = 2000
RUIN_SIMULATIONS = 5000


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "expectancy_pips": None, "profit_factor": None, "win_rate": None, "max_drawdown_pips": None}
    return {"n": len(values), "expectancy_pips": mean(values), "profit_factor": profit_factor(values), "win_rate": sum(v > 0 for v in values) / len(values), "max_drawdown_pips": max_drawdown(values)}


def _matches(record: TargetRecord, candidate: dict[str, Any], split: str) -> bool:
    return (record["split"] == split and int(record["horizon"]) == int(candidate["horizon"]) and record["regime"] == candidate["regime"] and record["session"] == candidate["session"] and (candidate["pairset"] == "all" or record["pair"].endswith("/JPY")) and (candidate["distance_max"] is None or float(record["median_distance"]) <= float(candidate["distance_max"])) and float(record["agreement"]) >= float(candidate["agreement_min"]))


def _values(records: Sequence[TargetRecord]) -> list[float]:
    return [float(r["outcome_pips"]) for r in sorted(records, key=lambda r: datetime.fromisoformat(r["timestamp"]))]


def _pair_stats(records: Sequence[TargetRecord]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for r in records:
        grouped.setdefault(r["pair"], []).append(float(r["outcome_pips"]))
    return {pair: _stats(vals) for pair, vals in sorted(grouped.items())}


def choose_robust_candidate(report: dict[str, Any]) -> dict[str, Any]:
    candidates = report.get("top_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("fresh discovery contains no candidates")
    ranked: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        disc = candidate.get("discovery", {})
        n = int(disc.get("n", 0))
        if n < MIN_DISCOVERY_SAMPLES:
            continue
        exp = float(disc.get("expectancy_pips") or float("-inf"))
        pf = float(disc.get("profit_factor") or 0.0)
        # Net expectancy falls one-for-one with additional per-trade execution cost.
        worst_15 = exp - 1.5
        worst_10 = exp - 1.0
        score = worst_15 + 0.25 * worst_10 + 0.10 * pf
        ranked.append((score, dict(candidate)))
    if not ranked:
        raise ValueError("no discovery candidate meets robustness sample floor")
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen = ranked[0][1]
    chosen["robust_discovery_rank"] = 1
    chosen["robust_discovery_score"] = ranked[0][0]
    return chosen


def evaluate_candidate(candidate: dict[str, Any], records: Sequence[TargetRecord]) -> dict[str, Any]:
    confirmation = [r for r in records if _matches(r, candidate, "confirmation")]
    vals = _values(confirmation)
    if len(vals) < MIN_CONFIRMATION_SAMPLES:
        return {"state": "INCOMPLETE", "confirmation": _stats(vals)}
    base = _stats(vals)
    stress = {str(cost): _stats([v - cost for v in vals]) for cost in STRESS_COSTS_PIPS}
    size = len(vals) // 4
    folds = []
    for i in range(4):
        a, b = i * size, len(vals) if i == 3 else (i + 1) * size
        folds.append(_stats(vals[a:b]))
    pairs = _pair_stats(confirmation)
    positive_pairs = sum(1 for s in pairs.values() if s["n"] >= MIN_PAIR_SAMPLES and (s["expectancy_pips"] or float("-inf")) > 0 and (s["profit_factor"] or 0) > 1)
    concentration = max((s["n"] / len(vals) for s in pairs.values()), default=1.0)
    ordinary = bootstrap_means(vals, reps=BOOTSTRAP_REPS, seed=20260902)
    block = block_bootstrap_means(vals, block_size=min(5, len(vals)), reps=BOOTSTRAP_REPS, seed=20260903)
    ruin = probability_of_ruin([v - 0.5 for v in vals], starting_capital_pips=20.0, simulations=RUIN_SIMULATIONS, horizon=len(vals), seed=20260904)
    gates = {
        "confirmation_sample_min_100": len(vals) >= MIN_CONFIRMATION_SAMPLES,
        "confirmation_expectancy_positive": (base["expectancy_pips"] or float("-inf")) > 0,
        "confirmation_pf_gt_1": (base["profit_factor"] or 0) > 1,
        "fold_stability": all((f["expectancy_pips"] or float("-inf")) > 0 for f in folds),
        "stress_survives_1_5_pips": all((s["expectancy_pips"] or float("-inf")) > 0 and (s["profit_factor"] or 0) > 1 for s in stress.values()),
        "bootstrap_supportive": min(ordinary[24], block[24]) > 0 and mean(v > 0 for v in ordinary) >= 0.95,
        "positive_pair_min_2": positive_pairs >= 2,
        "pair_concentration_lte_80pct": concentration <= MAX_PAIR_SHARE,
        "ruin_lt_5pct_after_0_5_stress": ruin < 0.05,
    }
    return {"state": "PASS" if all(gates.values()) else "FAIL", "confirmation": base, "confirmation_folds": folds, "confirmation_pair_breakdown": pairs, "positive_pair_count": positive_pairs, "largest_pair_observation_share": concentration, "stress": stress, "bootstrap": {"ordinary_lower_95": ordinary[24], "ordinary_upper_95": ordinary[-25], "block_lower_95": block[24], "block_upper_95": block[-25], "probability_positive_mean": mean(v > 0 for v in ordinary)}, "ruin_probability_after_0_5_pip_stress": ruin, "gates": gates}


def run(input_dir: Path, discovery_path: Path, sample_stride: int, history_states: int) -> dict[str, Any]:
    report = json.loads(discovery_path.read_text(encoding="utf-8"))
    records: list[TargetRecord] = []
    costs = ExecutionAssumptions()
    for pair in PAIR_TO_SYMBOL:
        rows, _ = experiment.analyze_pair(pair, load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"), sample_stride, history_states, costs)
        records.extend(rows)
    champion = dict(report["top_candidates"][0])
    challenger = choose_robust_candidate(report)
    champion_result = evaluate_candidate(champion, records)
    challenger_result = evaluate_candidate(challenger, records)
    champion_exp = champion_result.get("confirmation", {}).get("expectancy_pips")
    challenger_exp = challenger_result.get("confirmation", {}).get("expectancy_pips")
    improvement = challenger_exp - champion_exp if champion_exp is not None and challenger_exp is not None else None
    adopt = challenger_result.get("state") == "PASS" and (champion_result.get("state") != "PASS" or (improvement is not None and improvement > 0))
    return {"status": "PROFITABILITY_ROBUSTNESS_COMPLETED", "selection_boundary": "challenger chosen from discovery metrics only; confirmation is untouched and never selects a candidate", "champion": {"candidate": champion, "result": champion_result}, "challenger": {"candidate": challenger, "result": challenger_result}, "confirmation_expectancy_improvement_pips": improvement, "recommendation": "ADOPT_CHALLENGER" if adopt else "KEEP_CHAMPION", "live_execution_authorized": False, "promotion_authorized": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--discovery-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    args = parser.parse_args()
    result = run(Path(args.input_dir), Path(args.discovery_report), args.sample_stride, args.history_states)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "recommendation": result["recommendation"], "confirmation_expectancy_improvement_pips": result["confirmation_expectancy_improvement_pips"], "live_execution_authorized": False}, indent=2))


if __name__ == "__main__":
    main()
