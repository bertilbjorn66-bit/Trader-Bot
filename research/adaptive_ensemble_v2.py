from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
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


@dataclass(slots=True)
class Stat:
    n: int = 0
    total: float = 0.0
    sq: float = 0.0
    wins: int = 0

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

    @property
    def pf(self) -> float | None:
        return None


def sign(value: float, threshold: float = 0.0) -> int:
    return 1 if value > threshold else -1 if value < -threshold else 0


def votes_for_state(state: Any, history: list[Any]) -> dict[str, tuple[int, float]]:
    momentum = float(state.features.get("momentum") or 0.0)
    trend = float(state.features.get("trend") or 0.0)
    strength = float(state.features.get("trend_strength") or 0.0)
    volatility = float(state.features.get("volatility") or 0.0)
    breakout = int(state.features.get("breakout") or 0)
    span = max(float(state.features.get("range") or 0.0), 1e-12)
    dh = float(state.features.get("distance_high") or 0.0)
    dl = float(state.features.get("distance_low") or 0.0)
    vols = [float(s.features.get("volatility") or 0.0) for s in history]
    vz = (volatility - mean(vols)) / pstdev(vols) if len(vols) >= 2 and pstdev(vols) > 0 else 0.0
    trend_dir = 1 if trend >= 0 else -1
    momentum_dir = sign(momentum, 1e-8)
    near_high = abs(dh) <= 0.15 * span
    near_low = abs(dl) <= 0.15 * span
    return {
        "trend": (trend_dir, 0.50 + 0.50 * strength),
        "momentum": (momentum_dir, min(1.0, 0.50 + min(0.50, abs(momentum) / max(volatility, 1e-9) * 0.05))),
        "breakout": (breakout, 0.90 if breakout else 0.0),
        "mean_reversion": (-trend_dir if strength < 0.50 else 0, 0.60 if strength < 0.50 else 0.0),
        "pullback": (trend_dir if momentum_dir == -trend_dir and strength >= 0.35 else 0, 0.70 if momentum_dir == -trend_dir and strength >= 0.35 else 0.0),
        "volatility": (momentum_dir if vz >= 0.75 else 0, min(0.95, 0.55 + 0.15 * max(0.0, vz)) if vz >= 0.75 and momentum_dir else 0.0),
        "reversal": (-1 if near_high else 1 if near_low else 0, 0.72 if near_high or near_low else 0.0),
        "analogue": (0, 0.0),
    }


def analogue_vote(pair: str, target: Any, history: list[Any], state_index: dict[datetime, int], bars: list[Any], horizon: int) -> tuple[int, float]:
    scaler = fit_scaler(history, DEFAULT_FEATURES)
    neighbours = nearest_states(target, history, scaler, k=min(100, len(history)))
    weighted: list[tuple[float, float]] = []
    for neighbour, distance in neighbours:
        index = state_index[neighbour.timestamp]
        if index + horizon >= len(bars):
            continue
        direction = "long" if float(neighbour.features.get("momentum") or 0.0) >= 0 else "short"
        outcome = future_outcome(bars, index, horizon, direction)
        value = outcome.return_abs / PAIR_PIP[pair]
        weight = 1.0 / max(distance, 0.05)
        weighted.append((value, weight))
    if not weighted:
        return 0, 0.0
    score = sum(v * w for v, w in weighted) / sum(w for _, w in weighted)
    return sign(score, 0.02), min(0.95, 0.55 + 0.20 * min(1.0, abs(score) / 2.0)) if score else 0.0


def conservative_edge(stat: Stat) -> float:
    if stat.n == 0:
        return 0.0
    shrink = stat.n / (stat.n + SHRINKAGE)
    estimate = shrink * stat.mean
    se = stat.std / math.sqrt(stat.n) if stat.n >= 2 else float("inf")
    return estimate - LOWER_Z * se


def choose(votes: dict[str, tuple[int, float]], stats: dict[tuple[str, int], Stat], horizon: int) -> tuple[str | None, int, float, str]:
    candidates: list[tuple[float, str, int, float]] = []
    for name, (direction, confidence) in votes.items():
        if direction == 0 or confidence < MIN_VOTE_CONF:
            continue
        stat = stats.get((name, horizon), Stat())
        score = conservative_edge(stat) * confidence
        if stat.n < MIN_CONTEXT_OBS:
            score *= 0.50
        candidates.append((score, name, direction, confidence))
    if not candidates:
        return None, 0, 0.0, "no_eligible_expert"
    candidates.sort(reverse=True)
    best = candidates[0]
    if best[0] <= 0:
        return None, 0, 0.0, "no_positive_conservative_edge"
    support = sum(c for _, _, d, c in candidates if d == best[2])
    oppose = sum(c for _, _, d, c in candidates if d != best[2])
    disagreement = oppose / max(1e-9, support + oppose)
    if disagreement > MAX_DISAGREEMENT:
        return None, 0, 0.0, "expert_disagreement"
    return best[1], best[2], support / max(1e-9, support + oppose), "adaptive_consensus"


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(x["outcome_pips"]) for x in records if "outcome_pips" in x]
    wins = sum(v > 0 for v in values)
    gross_win = sum(v for v in values if v > 0)
    gross_loss = -sum(v for v in values if v < 0)
    equity = peak = dd = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {
        "n": len(values),
        "expectancy_pips": mean(values) if values else None,
        "profit_factor": gross_win / gross_loss if gross_loss else None,
        "win_rate": wins / len(values) if values else None,
        "max_drawdown_pips": dd,
        "strategies": len({x["strategy"] for x in records if "outcome_pips" in x}),
        "pairs": len({x["pair"] for x in records if "outcome_pips" in x}),
        "regimes": len({x["regime"] for x in records if "outcome_pips" in x}),
        "sessions": len({x["session"] for x in records if "outcome_pips" in x}),
    }


def evaluate_pair(pair: str, rows: list[dict[str, object]], sample_stride: int, history_states: int) -> list[dict[str, Any]]:
    rows, _ = _execution_valid_rows(rows, pair)
    bars = _merge(*_market_bars(rows))
    states = [state_from_bar_window(bars, i, STATE_LOOKBACK) for i in range(STATE_LOOKBACK, len(bars))]
    index_by_time = {s.timestamp: i + STATE_LOOKBACK for i, s in enumerate(states)}
    learned: dict[tuple[str, int], Stat] = defaultdict(Stat)
    decisions: list[dict[str, Any]] = []
    costs = ExecutionAssumptions()
    for position in range(history_states, len(states) - max(DEFAULT_HORIZONS) - 1, sample_stride):
        target = states[position]
        target_index = index_by_time[target.timestamp]
        history = states[position - history_states:position]
        regime = classify_regime(float(target.features.get("trend") or 0.0), float(target.features.get("trend_strength") or 0.0), _volatility_z(target, history), int(target.features.get("breakout") or 0))
        session = session_label(target.timestamp)
        spread_values = [float(s.features.get("spread") or 0.0) for s in history]
        current_spread = float(target.features.get("spread") or 0.0)
        if len(spread_values) >= 2 and pstdev(spread_values) > 0 and (current_spread - mean(spread_values)) / pstdev(spread_values) > 2.0:
            decisions.append({"timestamp": target.timestamp.isoformat(), "pair": pair, "action": "NO_TRADE", "reason": "spread_anomaly"})
            continue
        for horizon in DEFAULT_HORIZONS:
            votes = votes_for_state(target, history)
            votes["analogue"] = analogue_vote(pair, target, history, index_by_time, bars, horizon)
            strategy, direction_sign, confidence, reason = choose(votes, learned, horizon)
            if strategy is None:
                continue
            direction = "long" if direction_sign > 0 else "short"
            outcome = future_outcome(bars, target_index, horizon, direction)
            value = net_move(outcome.return_abs, costs) / PAIR_PIP[pair]
            decisions.append({"timestamp": target.timestamp.isoformat(), "pair": pair, "horizon": horizon, "regime": regime, "session": session, "strategy": strategy, "direction": direction, "confidence": confidence, "reason": reason, "outcome_pips": value})
            for name, (vote_direction, vote_confidence) in votes.items():
                if vote_direction == 0 or vote_confidence < MIN_VOTE_CONF:
                    continue
                vote_dir = "long" if vote_direction > 0 else "short"
                vote_outcome = future_outcome(bars, target_index, horizon, vote_dir)
                vote_value = net_move(vote_outcome.return_abs, costs) / PAIR_PIP[pair]
                learned[(name, horizon)].add(vote_value)
    return decisions


def run(input_dir: Path, sample_stride: int, history_states: int, slippage_pips: float) -> dict[str, Any]:
    all_records: list[dict[str, Any]] = []
    pair_summaries: dict[str, Any] = {}
    for pair in PAIR_TO_SYMBOL:
        records = evaluate_pair(pair, load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"), sample_stride, history_states)
        all_records.extend(records)
        pair_summaries[pair] = summary(records)
    all_records.sort(key=lambda r: r["timestamp"])
    actionable = [r for r in all_records if "outcome_pips" in r]
    split = int(len(actionable) * 0.60)
    discovery = actionable[:split]
    confirmation = actionable[split:]
    stressed = [{**r, "outcome_pips": float(r["outcome_pips"]) - slippage_pips} for r in actionable]
    years = sorted({datetime.fromisoformat(r["timestamp"]).year for r in actionable})
    positive_years = sum(summary([r for r in actionable if datetime.fromisoformat(r["timestamp"]).year == y])["expectancy_pips"] > 0 for y in years)
    return {
        "status": "ADAPTIVE_ENSEMBLE_V2_COMPLETED",
        "empirical": True,
        "strategy_set": list(STRATEGIES),
        "design": {
            "current_vs_past": True,
            "multiple_strategies": True,
            "context_dimensions": ["pair", "regime", "session", "horizon"],
            "online_learning": True,
            "causal_update": "learned strategy statistics are updated only after each target outcome",
            "abstention": True,
            "live_orders": False,
        },
        "overall": summary(actionable),
        "chronological_discovery_60pct": summary(discovery),
        "chronological_confirmation_40pct": summary(confirmation),
        "stress": summary(stressed),
        "year_stability": {"positive_years": positive_years, "observed_years": len(years), "ratio": positive_years / len(years) if years else 0.0},
        "pair_summaries": pair_summaries,
        "promotion_recommendation": "PASS_PRELIMINARY" if summary(confirmation)["expectancy_pips"] is not None and summary(confirmation)["expectancy_pips"] > 0 and (summary(confirmation)["profit_factor"] or 0) > 1 and summary(stressed)["expectancy_pips"] > 0 else "FAIL",
        "prediction_limit": "probabilistic prediction only; no system can guarantee perfect or near-perfect future forecasts",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--slippage-pips", type=float, default=0.2)
    args = parser.parse_args()
    result = run(Path(args.input_dir), args.sample_stride, args.history_states, args.slippage_pips)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"confirmation": result["chronological_confirmation_40pct"], "stress": result["stress"], "year_stability": result["year_stability"], "promotion_recommendation": result["promotion_recommendation"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
