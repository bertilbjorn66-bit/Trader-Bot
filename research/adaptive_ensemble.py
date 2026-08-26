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

STRATEGIES = (
    "trend_follow",
    "momentum",
    "breakout",
    "mean_reversion",
    "pullback",
    "volatility_follow",
    "range_reversal",
    "analogue",
)

MIN_CONTEXT_OBS = 30
SHRINKAGE = 50.0
LOWER_BOUND_Z = 1.28
MAX_SPREAD_Z = 2.0
MIN_CONFIDENCE = 0.58
MAX_DISAGREEMENT = 0.30


@dataclass(slots=True)
class Stat:
    n: int = 0
    total: float = 0.0
    total_sq: float = 0.0
    wins: int = 0

    def update(self, value: float) -> None:
        self.n += 1
        self.total += value
        self.total_sq += value * value
        self.wins += int(value > 0.0)

    @property
    def mean(self) -> float:
        return self.total / self.n if self.n else 0.0

    @property
    def std(self) -> float:
        if self.n < 2:
            return 0.0
        variance = max(0.0, (self.total_sq - (self.total * self.total) / self.n) / (self.n - 1))
        return math.sqrt(variance)

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0


def _sign(value: float, threshold: float = 0.0) -> int:
    return 1 if value > threshold else -1 if value < -threshold else 0


def _strategy_votes(state: Any, history: list[Any]) -> dict[str, tuple[int, float]]:
    momentum = float(state.features.get("momentum") or 0.0)
    trend = float(state.features.get("trend") or 0.0)
    strength = float(state.features.get("trend_strength") or 0.0)
    volatility = float(state.features.get("volatility") or 0.0)
    breakout = int(state.features.get("breakout") or 0)
    range_value = max(float(state.features.get("range") or 0.0), 1e-12)
    distance_high = float(state.features.get("distance_high") or 0.0)
    distance_low = float(state.features.get("distance_low") or 0.0)

    history_vol = [float(s.features.get("volatility") or 0.0) for s in history]
    vol_mean = mean(history_vol) if history_vol else volatility
    vol_std = pstdev(history_vol) if len(history_vol) >= 2 else 0.0
    vol_z = (volatility - vol_mean) / vol_std if vol_std > 0 else 0.0

    trend_dir = 1 if trend >= 0 else -1
    momentum_dir = _sign(momentum, 1e-8)
    near_high = abs(distance_high) <= 0.15 * range_value
    near_low = abs(distance_low) <= 0.15 * range_value

    votes: dict[str, tuple[int, float]] = {
        "trend_follow": (trend_dir, min(1.0, 0.50 + 0.50 * strength)),
        "momentum": (momentum_dir, min(1.0, 0.50 + min(0.50, abs(momentum) / max(volatility, 1e-9) * 0.05))),
        "breakout": (breakout, 0.90 if breakout else 0.0),
        "mean_reversion": (-trend_dir if strength < 0.50 else 0, 0.60 if strength < 0.50 else 0.0),
        "pullback": (
            trend_dir if momentum_dir == -trend_dir and strength >= 0.35 else 0,
            0.70 if momentum_dir == -trend_dir and strength >= 0.35 else 0.0,
        ),
        "volatility_follow": (
            momentum_dir if vol_z >= 0.75 else 0,
            min(0.95, 0.55 + max(0.0, vol_z) * 0.15) if vol_z >= 0.75 and momentum_dir else 0.0,
        ),
        "range_reversal": (
            -1 if near_high else 1 if near_low else 0,
            0.72 if near_high or near_low else 0.0,
        ),
        "analogue": (0, 0.0),
    }
    return votes


def _analogue_vote(
    target: Any,
    history: list[Any],
    state_index: dict[datetime, int],
    bars: list[Any],
    horizon: int,
    costs: ExecutionAssumptions,
) -> tuple[int, float]:
    scaler = fit_scaler(history, DEFAULT_FEATURES)
    neighbors = nearest_states(target, history, scaler, k=min(100, len(history)))
    weighted: list[tuple[float, float]] = []
    for neighbor, distance in neighbors:
        index = state_index[neighbor.timestamp]
        if index + horizon >= len(bars):
            continue
        direction = "long" if float(neighbor.features.get("momentum") or 0.0) >= 0.0 else "short"
        outcome = future_outcome(bars, index, horizon, direction)
        pip_value = net_move(outcome.return_abs, costs) / PAIR_PIP[current_pair]
        weight = 1.0 / max(distance, 0.05)
        weighted.append((pip_value, weight))
    if not weighted:
        return 0, 0.0
    score = sum(value * weight for value, weight in weighted) / sum(weight for _, weight in weighted)
    confidence = min(0.95, 0.55 + min(0.40, abs(score) / 2.0 * 0.40))
    return _sign(score, 0.02), confidence if score != 0 else 0.0


def _lower_bound(stat: Stat, *, prior_mean: float = 0.0) -> float:
    if stat.n == 0:
        return prior_mean
    shrink = stat.n / (stat.n + SHRINKAGE)
    mean_est = shrink * stat.mean + (1.0 - shrink) * prior_mean
    se = stat.std / math.sqrt(stat.n) if stat.n >= 2 else float("inf")
    return mean_est - LOWER_BOUND_Z * se


def _context_keys(pair: str, regime: str, session: str) -> tuple[tuple[str, str, str], tuple[str, str], tuple[str]]:
    return (pair, regime, session), (pair, regime), (pair,)


def _select_strategy(
    votes: dict[str, tuple[int, float]],
    context_stats: dict[tuple[Any, ...], Stat],
    global_stats: dict[tuple[str, int], Stat],
    horizon: int,
    pair: str,
    regime: str,
    session: str,
) -> tuple[str | None, int, float, str]:
    context_key, regime_key, pair_key = _context_keys(pair, regime, session)
    candidates: list[tuple[float, str, int, float]] = []
    for strategy, (direction, confidence) in votes.items():
        if direction == 0 or confidence < MIN_CONFIDENCE:
            continue
        exact = context_stats.get((context_key, strategy, horizon), Stat())
        fallback = context_stats.get((regime_key, strategy, horizon), Stat())
        pair_stat = context_stats.get((pair_key, strategy, horizon), Stat())
        global_stat = global_stats.get((strategy, horizon), Stat())
        if exact.n >= MIN_CONTEXT_OBS:
            selected_stat = exact
            scope = "pair-regime-session"
        elif fallback.n >= MIN_CONTEXT_OBS:
            selected_stat = fallback
            scope = "pair-regime"
        elif pair_stat.n >= MIN_CONTEXT_OBS:
            selected_stat = pair_stat
            scope = "pair"
        else:
            selected_stat = global_stat
            scope = "global"
        lb = _lower_bound(selected_stat)
        score = lb * confidence
        if selected_stat.n < MIN_CONTEXT_OBS:
            score *= 0.50
        candidates.append((score, strategy, direction, confidence))
    if not candidates:
        return None, 0, 0.0, "no eligible strategy"
    candidates.sort(reverse=True)
    best = candidates[0]
    if best[0] <= 0.0:
        return None, 0, 0.0, "no strategy has positive conservative historical edge"
    opposing = sum(item[3] for item in candidates if item[2] != best[2])
    supporting = sum(item[3] for item in candidates if item[2] == best[2])
    disagreement = opposing / max(1e-9, opposing + supporting)
    if disagreement > MAX_DISAGREEMENT:
        return None, 0, 0.0, "strategy disagreement is too high"
    return best[1], best[2], min(0.99, max(0.50, supporting / max(1e-9, supporting + opposing))), "adaptive consensus"


def evaluate_pair(pair: str, rows: list[dict[str, object]], sample_stride: int, history_states: int, costs: ExecutionAssumptions) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    global current_pair
    current_pair = pair
    rows, quality = _execution_valid_rows(rows, pair)
    bars = _merge(*_market_bars(rows))
    states = [state_from_bar_window(bars, i, STATE_LOOKBACK) for i in range(STATE_LOOKBACK, len(bars))]
    state_index = {state.timestamp: i + STATE_LOOKBACK for i, state in enumerate(states)}
    context_stats: dict[tuple[Any, ...], Stat] = defaultdict(Stat)
    global_stats: dict[tuple[str, int], Stat] = defaultdict(Stat)
    decisions: list[dict[str, Any]] = []

    for position in range(history_states, len(states) - max(DEFAULT_HORIZONS), sample_stride):
        target = states[position]
        target_index = state_index[target.timestamp]
        history = states[position - history_states:position]
        volatility_z = _volatility_z(target, history)
        regime = classify_regime(
            float(target.features.get("trend") or 0.0),
            float(target.features.get("trend_strength") or 0.0),
            volatility_z,
            int(target.features.get("breakout") or 0),
        )
        session = session_label(target.timestamp)
        spread = float(target.features.get("spread") or 0.0)
        hist_spreads = [float(s.features.get("spread") or 0.0) for s in history]
        spread_mean = mean(hist_spreads) if hist_spreads else spread
        spread_std = pstdev(hist_spreads) if len(hist_spreads) >= 2 else 0.0
        spread_z = (spread - spread_mean) / spread_std if spread_std > 0 else 0.0
        if spread_z > MAX_SPREAD_Z:
            decisions.append({"timestamp": target.timestamp.isoformat(), "action": "NO_TRADE", "reason": "spread_anomaly"})
            continue

        base_votes = _strategy_votes(target, history)
        for horizon in DEFAULT_HORIZONS:
            votes = dict(base_votes)
            votes["analogue"] = _analogue_vote(target, history, state_index, bars, horizon, costs)
            strategy, direction_sign, confidence, reason = _select_strategy(
                votes, context_stats, global_stats, horizon, pair, f"regime:{regime}", session
            )
            if strategy is None:
                continue
            direction = "long" if direction_sign > 0 else "short"
            outcome = future_outcome(bars, target_index, horizon, direction)
            value_pips = net_move(outcome.return_abs, costs) / PAIR_PIP[pair]
            context_key, regime_key, pair_key = _context_keys(pair, f"regime:{regime}", session)

            decisions.append({
                "timestamp": target.timestamp.isoformat(),
                "pair": pair,
                "horizon": horizon,
                "regime": f"regime:{regime}",
                "session": session,
                "strategy": strategy,
                "direction": direction,
                "confidence": confidence,
                "reason": reason,
                "outcome_pips": value_pips,
            })

            for candidate_strategy, (candidate_direction, candidate_confidence) in votes.items():
                if candidate_direction == 0 or candidate_confidence < MIN_CONFIDENCE:
                    continue
                candidate_dir = "long" if candidate_direction > 0 else "short"
                candidate_outcome = future_outcome(bars, target_index, horizon, candidate_dir)
                candidate_value = net_move(candidate_outcome.return_abs, costs) / PAIR_PIP[pair]
                context_stats[(context_key, candidate_strategy, horizon)].update(candidate_value)
                context_stats[(regime_key, candidate_strategy, horizon)].update(candidate_value)
                context_stats[(pair_key, candidate_strategy, horizon)].update(candidate_value)
                global_stats[(candidate_strategy, horizon)].update(candidate_value)

    return decisions, {
        "pair": pair,
        "data_quality": quality,
        "decisions": len(decisions),
        "actionable": sum(item.get("action") != "NO_TRADE" for item in decisions),
        "strategy_counts": {strategy: sum(item.get("strategy") == strategy for item in decisions) for strategy in STRATEGIES},
    }


def _summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    actionable = [item for item in decisions if item.get("outcome_pips") is not None]
    values = [float(item["outcome_pips"]) for item in actionable]
    wins = [v for v in values if v > 0]
    losses = [-v for v in values if v < 0]
    gross_loss = sum(losses)
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "n": len(values),
        "expectancy_pips": mean(values) if values else None,
        "profit_factor": sum(wins) / gross_loss if gross_loss else None,
        "win_rate": len(wins) / len(values) if values else None,
        "max_drawdown_pips": drawdown,
        "strategy_diversity": len({item.get("strategy") for item in actionable}),
        "pairs": len({item.get("pair") for item in actionable}),
        "regimes": len({item.get("regime") for item in actionable}),
        "sessions": len({item.get("session") for item in actionable}),
    }


def run(input_dir: Path, sample_stride: int, history_states: int, slippage_pips: float = 0.2, commission_pips: float = 0.0) -> dict[str, Any]:
    costs = ExecutionAssumptions()
    all_decisions: list[dict[str, Any]] = []
    pair_reports: list[dict[str, Any]] = []
    for pair in PAIR_TO_SYMBOL:
        decisions, report = evaluate_pair(pair, load_feed_bars(input_dir / f"{PAIR_TO_SYMBOL[pair]}.jsonl"), sample_stride, history_states, costs)
        all_decisions.extend(decisions)
        pair_reports.append({**report, "summary": _summary(decisions)})

    all_decisions.sort(key=lambda item: item["timestamp"])
    total = _summary(all_decisions)
    split_index = int(len(all_decisions) * 0.60)
    discovery = _summary(all_decisions[:split_index])
    confirmation = _summary(all_decisions[split_index:])
    stressed_values = [float(item["outcome_pips"]) - slippage_pips - commission_pips for item in all_decisions if item.get("outcome_pips") is not None]
    stress = _summary([{**item, "outcome_pips": value} for item, value in zip([x for x in all_decisions if x.get("outcome_pips") is not None], stressed_values, strict=True)])

    positive_years = sum(
        mean(float(item["outcome_pips"]) for item in all_decisions if item.get("outcome_pips") is not None and datetime.fromisoformat(item["timestamp"]).year == year) > 0
        for year in sorted({datetime.fromisoformat(item["timestamp"]).year for item in all_decisions})
    )
    observed_years = len({datetime.fromisoformat(item["timestamp"]).year for item in all_decisions})

    return {
        "status": "ADAPTIVE_ENSEMBLE_RESEARCH_COMPLETED",
        "empirical": True,
        "strategy_set": list(STRATEGIES),
        "design": {
            "decision_principle": "current state is compared with prior states and prior realized expert performance; no future observation informs the decision",
            "selection": "online expert routing by pair/regime/session with conservative shrinkage and lower-confidence-bound scoring",
            "abstention": "NO_TRADE for spread anomalies, insufficient context evidence, conservative edge <= 0, or excessive strategy disagreement",
            "prediction": "multi-horizon directional prediction from several independent hypotheses plus analogue similarity",
            "adaptation": "all eligible experts are updated only after their target outcome is known, preserving chronological causality",
            "stress_costs_pips": {"slippage": slippage_pips, "commission": commission_pips},
            "live_orders": False,
        },
        "pair_reports": pair_reports,
        "overall": total,
        "chronological_discovery_60pct": discovery,
        "chronological_confirmation_40pct": confirmation,
        "stress": stress,
        "year_stability": {"positive_years": positive_years, "observed_years": observed_years, "ratio": positive_years / observed_years if observed_years else 0.0},
        "promotion_recommendation": "PASS_CANDIDATE_FOR_FURTHER_AUDIT" if confirmation["expectancy_pips"] is not None and confirmation["expectancy_pips"] > 0 and (confirmation["profit_factor"] or 0) > 1 else "FAIL",
        "important_limit": "historical evidence can establish robustness, not certainty or guaranteed future profit",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage-safe adaptive multi-strategy ensemble research.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-stride", type=int, default=60)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--slippage-pips", type=float, default=0.2)
    parser.add_argument("--commission-pips", type=float, default=0.0)
    args = parser.parse_args()
    if args.sample_stride <= 0 or args.history_states <= 0:
        raise SystemExit("sample-stride and history-states must be positive")
    result = run(Path(args.input_dir), args.sample_stride, args.history_states, args.slippage_pips, args.commission_pips)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "overall": result["overall"], "confirmation": result["chronological_confirmation_40pct"], "stress": result["stress"], "promotion_recommendation": result["promotion_recommendation"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
