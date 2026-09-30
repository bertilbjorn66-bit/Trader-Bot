from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .cross_section import session_label
from .datafeed_empirical import PAIR_TO_SYMBOL, _execution_valid_rows, _market_bars, load_feed_bars
from .execution import ExecutionAssumptions, net_move
from .outcomes import future_outcome
from .pipeline import state_from_bar_window
from .regimes import classify_regime
from .sequential_empirical import DEFAULT_HORIZONS, STATE_LOOKBACK, _merge, _volatility_z
from .similarity import DEFAULT_FEATURES, fit_scaler, nearest_states

PAIR_PIP = {
    "EUR/USD": 0.0001, "GBP/USD": 0.0001, "USD/JPY": 0.01,
    "AUD/USD": 0.0001, "USD/CAD": 0.0001, "USD/CHF": 0.0001,
    "NZD/USD": 0.0001, "EUR/JPY": 0.01, "GBP/JPY": 0.01,
}
STRATEGIES = ("trend", "momentum", "breakout", "mean_reversion", "pullback", "volatility", "reversal", "analogue")
MIN_CONTEXT_OBS = 30
SHRINKAGE = 50.0
LOWER_Z = 1.28
MIN_VOTE_CONF = 0.58
MAX_DISAGREEMENT = 0.30
MAX_SPREAD_Z = 2.0


class Stat:
    def __init__(self) -> None:
        self.n = 0
        self.total = 0.0
        self.sq = 0.0
        self.wins = 0

    def add(self, value: float) -> None:
        self.n += 1
        self.total += value
        self.sq += value * value
        self.wins += int(value > 0.0)

    @property
    def mean(self) -> float:
        return self.total / self.n if self.n else 0.0

    @property
    def std(self) -> float:
        if self.n < 2:
            return 0.0
        variance = max(0.0, (self.sq - self.total * self.total / self.n) / (self.n - 1))
        return math.sqrt(variance)


def _sign(value: float, threshold: float = 0.0) -> int:
    return 1 if value > threshold else -1 if value < -threshold else 0


def strategy_votes(state: Any, history: list[Any]) -> dict[str, tuple[int, float]]:
    momentum = float(state.features.get("momentum") or 0.0)
    trend = float(state.features.get("trend") or 0.0)
    strength = float(state.features.get("trend_strength") or 0.0)
    volatility = float(state.features.get("volatility") or 0.0)
    breakout = int(state.features.get("breakout") or 0)
    span = max(float(state.features.get("range") or 0.0), 1e-12)
    distance_high = float(state.features.get("distance_high") or 0.0)
    distance_low = float(state.features.get("distance_low") or 0.0)
    vols = [float(item.features.get("volatility") or 0.0) for item in history]
    vol_std = pstdev(vols) if len(vols) >= 2 else 0.0
    vol_z = (volatility - mean(vols)) / vol_std if vol_std else 0.0
    trend_dir = 1 if trend >= 0 else -1
    momentum_dir = _sign(momentum, 1e-8)
    near_high = abs(distance_high) <= 0.15 * span
    near_low = abs(distance_low) <= 0.15 * span
    return {
        "trend": (trend_dir, min(1.0, 0.50 + 0.50 * strength)),
        "momentum": (momentum_dir, min(1.0, 0.50 + min(0.50, abs(momentum) / max(volatility, 1e-9) * 0.05))),
        "breakout": (breakout, 0.90 if breakout else 0.0),
        "mean_reversion": (-trend_dir if strength < 0.50 else 0, 0.60 if strength < 0.50 else 0.0),
        "pullback": (trend_dir if momentum_dir == -trend_dir and strength >= 0.35 else 0, 0.70 if momentum_dir == -trend_dir and strength >= 0.35 else 0.0),
        "volatility": (momentum_dir if vol_z >= 0.75 else 0, min(0.95, 0.55 + 0.15 * max(vol_z, 0.0)) if vol_z >= 0.75 and momentum_dir else 0.0),
        "reversal": (-1 if near_high else 1 if near_low else 0, 0.72 if near_high or near_low else 0.0),
        "analogue": (0, 0.0),
    }


def conservative_edge(stat: Stat) -> float:
    if stat.n == 0:
        return 0.0
    shrink = stat.n / (stat.n + SHRINKAGE)
    estimate = shrink * stat.mean
    se = stat.std / math.sqrt(stat.n) if stat.n >= 2 else float("inf")
    return estimate - LOWER_Z * se


def _context_keys(pair: str, regime: str, session: str) -> tuple[tuple[str, str, str], tuple[str, str], tuple[str]]:
    return (pair, regime, session), (pair, regime), (pair,)


def _stat_for(local: dict[tuple[Any, ...], Stat], global_stats: dict[tuple[str, int], Stat], name: str, horizon: int, pair: str, regime: str, session: str) -> Stat:
    exact_key, regime_key, pair_key = _context_keys(pair, regime, session)
    exact = local.get((exact_key, name, horizon))
    fallback = local.get((regime_key, name, horizon))
    pair_stat = local.get((pair_key, name, horizon))
    if exact is not None and exact.n >= MIN_CONTEXT_OBS:
        return exact
    if fallback is not None and fallback.n >= MIN_CONTEXT_OBS:
        return fallback
    if pair_stat is not None and pair_stat.n >= MIN_CONTEXT_OBS:
        return pair_stat
    return global_stats.get((name, horizon), Stat())


def analogue_vote(pair: str, target: Any, history: list[Any], state_index: dict[datetime, int], bars: list[Any], horizon: int, costs: ExecutionAssumptions) -> tuple[int, float]:
    scaler = fit_scaler(history, DEFAULT_FEATURES)
    neighbours = nearest_states(target, history, scaler, k=min(100, len(history)))
    target_index = state_index[target.timestamp]
    weighted: list[tuple[float, float]] = []
    for neighbour, distance in neighbours:
        index = state_index[neighbour.timestamp]
        if index + horizon >= target_index:
            continue
        direction = "long" if float(neighbour.features.get("momentum") or 0.0) >= 0.0 else "short"
        outcome = future_outcome(bars, index, horizon, direction)
        value = net_move(outcome.return_abs, costs) / PAIR_PIP[pair]
        weighted.append((value, 1.0 / max(distance, 0.05)))
    if not weighted:
        return 0, 0.0
    score = sum(value * weight for value, weight in weighted) / sum(weight for _, weight in weighted)
    confidence = min(0.95, 0.55 + min(0.40, abs(score) / 2.0 * 0.40))
    return _sign(score, 0.02), confidence if score else 0.0


def route(votes: dict[str, tuple[int, float]], local: dict[tuple[Any, ...], Stat], global_stats: dict[tuple[str, int], Stat], horizon: int, pair: str, regime: str, session: str) -> tuple[str | None, int, float, str]:
    scored: list[tuple[float, str, int, float]] = []
    for name, (direction, confidence) in votes.items():
        if direction == 0 or confidence < MIN_VOTE_CONF:
            continue
        stat = _stat_for(local, global_stats, name, horizon, pair, regime, session)
        edge = conservative_edge(stat)
        if stat.n < MIN_CONTEXT_OBS:
            edge *= 0.5
        scored.append((edge * confidence, name, direction, confidence))
    if not scored:
        return None, 0, 0.0, "no_eligible_expert"
    supporting = sum(max(score, 0.0) for score, _, direction, _ in scored if direction > 0)
    opposing = sum(max(score, 0.0) for score, _, direction, _ in scored if direction < 0)
    total = supporting + opposing
    if total <= 0.0:
        return None, 0, 0.0, "no_positive_ensemble_edge"
    disagreement = min(supporting, opposing) / total
    if disagreement > MAX_DISAGREEMENT:
        return None, 0, 0.0, "ensemble_disagreement"
    direction = 1 if supporting > opposing else -1
    confidence = max(supporting, opposing) / total
    lead = max(scored, key=lambda item: item[0])[1]
    if confidence < 1.0 - MAX_DISAGREEMENT:
        return None, 0, confidence, "ensemble_confidence_too_low"
    return lead, direction, min(0.99, confidence), "multi_expert_consensus"


def summary(records: list[dict[str, Any]], extra_cost_pips: float = 0.0) -> dict[str, Any]:
    values = [float(item["outcome_pips"]) - extra_cost_pips for item in records]
    wins = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "n": len(values),
        "expectancy_pips": mean(values) if values else None,
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_pips": drawdown if values else None,
    }


def evaluate_pair(pair: str, rows: list[dict[str, object]], sample_stride: int, history_states: int, costs: ExecutionAssumptions) -> list[dict[str, Any]]:
    rows, _quality = _execution_valid_rows(rows, pair)
    bars = _merge(*_market_bars(rows))
    states = [state_from_bar_window(bars, i, STATE_LOOKBACK) for i in range(STATE_LOOKBACK, len(bars))]
    state_index = {state.timestamp: i + STATE_LOOKBACK for i, state in enumerate(states)}
    local: dict[tuple[Any, ...], Stat] = defaultdict(Stat)
    global_stats: dict[tuple[str, int], Stat] = defaultdict(Stat)
    decisions: list[dict[str, Any]] = []
    for position in range(history_states, len(states) - max(DEFAULT_HORIZONS), sample_stride):
        target = states[position]
        target_index = state_index[target.timestamp]
        history = states[position - history_states : position]
        regime = classify_regime(float(target.features.get("trend") or 0.0), float(target.features.get("trend_strength") or 0.0), _volatility_z(target, history), int(target.features.get("breakout") or 0))
        session = session_label(target.timestamp)
        spreads = [float(item.features.get("spread") or 0.0) for item in history]
        current_spread = float(target.features.get("spread") or 0.0)
        spread_std = pstdev(spreads) if len(spreads) >= 2 else 0.0
        spread_z = (current_spread - mean(spreads)) / spread_std if spread_std else 0.0
        if spread_z > MAX_SPREAD_Z:
            continue
        pending: list[tuple[str, int, int]] = []
        base_votes = strategy_votes(target, history)
        for horizon in DEFAULT_HORIZONS:
            votes = dict(base_votes)
            votes["analogue"] = analogue_vote(pair, target, history, state_index, bars, horizon, costs)
            lead, direction_sign, confidence, reason = route(votes, local, global_stats, horizon, pair, f"regime:{regime}", session)
            if lead is not None:
                direction = "long" if direction_sign > 0 else "short"
                outcome = future_outcome(bars, target_index, horizon, direction)
                value = net_move(outcome.return_abs, costs) / PAIR_PIP[pair]
                decisions.append({"timestamp": target.timestamp.isoformat(), "pair": pair, "horizon": horizon, "regime": f"regime:{regime}", "session": session, "strategy": lead, "direction": direction, "confidence": confidence, "reason": reason, "outcome_pips": value})
            for name, (vote_direction, vote_confidence) in votes.items():
                if vote_direction and vote_confidence >= MIN_VOTE_CONF:
                    pending.append((name, horizon, vote_direction))
        exact_key, regime_key, pair_key = _context_keys(pair, f"regime:{regime}", session)
        for name, horizon, vote_direction in pending:
            direction = "long" if vote_direction > 0 else "short"
            outcome = future_outcome(bars, target_index, horizon, direction)
            value = net_move(outcome.return_abs, costs) / PAIR_PIP[pair]
            local[(exact_key, name, horizon)].add(value)
            local[(regime_key, name, horizon)].add(value)
            local[(pair_key, name, horizon)].add(value)
            global_stats[(name, horizon)].add(value)
    return decisions


def run(input_dir: Path, sample_stride: int, history_states: int, slippage_pips: float, commission_pips: float) -> dict[str, Any]:
    if sample_stride <= 0 or history_states <= 0 or slippage_pips < 0 or commission_pips < 0:
        raise ValueError("invalid research parameters")
    all_records: list[dict[str, Any]] = []
    pair_summaries: dict[str, Any] = {}
    for pair in PAIR_TO_SYMBOL:
        pip = PAIR_PIP[pair]
        costs = ExecutionAssumptions(slippage=slippage_pips * pip, commission=commission_pips * pip)
        records = evaluate_pair(pair, load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"), sample_stride, history_states, costs)
        all_records.extend(records)
        pair_summaries[pair] = summary(records)
    ordered = sorted(all_records, key=lambda item: datetime.fromisoformat(item["timestamp"]))
    split = int(len(ordered) * 0.60)
    discovery = ordered[:split]
    confirmation = ordered[split:]
    stress = {str(cost): summary(confirmation, cost) for cost in (0.0, 0.2, 0.5, 1.0, 1.5)}
    years: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in confirmation:
        years[str(datetime.fromisoformat(item["timestamp"]).year)].append(item)
    year_reports = {year: summary(rows) for year, rows in sorted(years.items())}
    positive_years = sum(bool(item["expectancy_pips"] is not None and item["expectancy_pips"] > 0) for item in year_reports.values())
    base = summary(confirmation)
    hard = stress["1.5"]
    preliminary = bool(base["n"] >= 100 and base["expectancy_pips"] and base["expectancy_pips"] > 0 and (base["profit_factor"] or 0) > 1 and hard["expectancy_pips"] and hard["expectancy_pips"] > 0 and (hard["profit_factor"] or 0) > 1 and (positive_years / len(year_reports) if year_reports else 0.0) >= 0.67)
    return {
        "status": "ADAPTIVE_ENSEMBLE_V4_COMPLETED", "empirical": True, "synthetic": False,
        "strategy_set": list(STRATEGIES), "decision_count": len(ordered), "pair_summaries": pair_summaries,
        "overall": summary(ordered), "chronological_discovery_60pct": summary(discovery), "chronological_confirmation_40pct": base,
        "stress": stress, "year_stability": {"years": year_reports, "positive_year_count": positive_years, "observed_year_count": len(year_reports), "positive_year_fraction": positive_years / len(year_reports) if year_reports else 0.0},
        "design": {"multi_expert_consensus": True, "current_vs_past": True, "online_learning": True, "same_timestamp_cross_horizon_leakage_blocked": True, "analogue_future_window_must_end_before_target": True, "abstain_on_disagreement": True, "live_orders": False},
        "promotion_recommendation": "PRELIMINARY_PASS" if preliminary else "NOT_READY", "promotion_authorized": False, "live_execution_authorized": False,
        "warning": "Non-live research only; no historical test can guarantee future profitability or perfect prediction.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Adaptive multi-expert context-aware empirical research v4.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--slippage-pips", type=float, default=0.2)
    parser.add_argument("--commission-pips", type=float, default=0.0)
    args = parser.parse_args()
    result = run(Path(args.input_dir), args.sample_stride, args.history_states, args.slippage_pips, args.commission_pips)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"confirmation": result["chronological_confirmation_40pct"], "stress_1_5": result["stress"]["1.5"], "year_stability": result["year_stability"], "promotion_recommendation": result["promotion_recommendation"]}, sort_keys=True))
    print("LIVE_EXECUTION_AUTHORIZED=false")


if __name__ == "__main__":
    main()
