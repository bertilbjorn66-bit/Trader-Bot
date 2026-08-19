from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from statistics import mean
from typing import Sequence

from .outcomes import future_outcome
from .risk import ExecutionAssumptions, net_move
from .similarity import DEFAULT_FEATURES, fit_scaler, nearest_states
from .statistics import expectancy, max_drawdown, probability_summary
from .types import Bar, State
from .validation import ensure_time_order


def state_from_bar_window(bars: Sequence[Bar], index: int, lookback: int = 20) -> State:
    if index < lookback or index >= len(bars):
        raise ValueError("insufficient history for state")
    window = bars[index - lookback : index + 1]
    closes = [b.bid_close for b in window]
    ranges = [b.bid_high - b.bid_low for b in window]
    mean_close = mean(closes)
    trend = 1 if closes[-1] >= mean_close else -1
    momentum = (closes[-1] - closes[-6]) / closes[-6] if closes[-6] else 0.0
    volatility = mean(ranges) / mean_close if mean_close else 0.0
    mean_range = mean(ranges)
    trend_strength = min(1.0, abs(closes[-1] - closes[0]) / (mean_range * lookback + 1e-12))
    recent_high = max(closes[:-1])
    recent_low = min(closes[:-1])
    breakout = 1 if closes[-1] > recent_high else -1 if closes[-1] < recent_low else 0
    return State(
        bars[index].timestamp,
        {
            "trend": trend,
            "trend_strength": trend_strength,
            "momentum": momentum,
            "volatility": volatility,
            "atr": mean_range,
            "range": max(closes) - min(closes),
            "distance_high": closes[-1] - recent_high,
            "distance_low": closes[-1] - recent_low,
            "spread": bars[index].spread,
            "breakout": breakout,
        },
    )


def build_states(bars: Sequence[Bar], lookback: int = 20) -> list[State]:
    ensure_time_order([State(b.timestamp, {}) for b in bars])
    return [state_from_bar_window(bars, i, lookback) for i in range(lookback, len(bars))]


def research_snapshot(
    bars: Sequence[Bar],
    target_index: int,
    horizon: int = 10,
    k: int = 50,
    costs: ExecutionAssumptions | None = None,
) -> dict[str, object]:
    if costs is None:
        costs = ExecutionAssumptions()
    states = build_states(bars)
    target_state = next(s for s in states if s.timestamp == bars[target_index].timestamp)
    historical = [s for s in states if s.timestamp < target_state.timestamp]
    scaler = fit_scaler(historical, DEFAULT_FEATURES)
    neighbors = nearest_states(target_state, historical, scaler, k=k)
    direction = "long" if float(target_state.features["momentum"]) >= 0 else "short"
    outcomes: list[float] = []
    mfe: list[float] = []
    mae: list[float] = []
    neighbor_times = {s.timestamp for s, _ in neighbors}
    for idx, bar in enumerate(bars):
        if bar.timestamp in neighbor_times and idx + horizon < len(bars):
            outcome = future_outcome(bars, idx, horizon, direction)
            outcomes.append(outcome.return_abs)
            mfe.append(outcome.mfe_abs)
            mae.append(outcome.mae_abs)
    spread = target_state.features["spread"]
    costed = [net_move(v, float(spread), costs) for v in outcomes]
    return {
        "timestamp": target_state.timestamp.isoformat(),
        "direction": direction,
        "neighbors": len(neighbors),
        "probability": probability_summary(costed),
        "expectancy": expectancy(costed),
        "mfe_mean": mean(mfe) if mfe else None,
        "mae_mean": mean(mae) if mae else None,
        "max_drawdown": max_drawdown(costed),
        "empirical": False,
        "warning": "SYNTHETIC OR UNPOPULATED UNTIL REAL MARKET DATA IS PROVIDED" if bars else "NO DATA",
    }


def snapshot_as_jsonable(snapshot: dict[str, object]) -> dict[str, object]:
    return {k: (v.isoformat() if isinstance(v, datetime) else asdict(v) if hasattr(v, "__dataclass_fields__") else v) for k, v in snapshot.items()}
