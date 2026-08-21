from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from trader_bot.models import MarketBar, Timeframe
from trader_bot.providers.dukascopy import DukascopyProvider

from .cross_section import session_label
from .execution import ExecutionAssumptions, net_move, validate_spread
from .historical_scan import iter_bid_ask_batches
from .outcomes import future_outcome
from .pipeline import state_from_bar_window
from .regimes import classify_regime
from .similarity import DEFAULT_FEATURES, fit_scaler, nearest_states
from .statistics import expectancy, max_drawdown, probability_summary
from .types import Bar, State
from .validation import expanding_walk_forward

TIMEFRAMES = {
    "1min": Timeframe.ONE_MINUTE,
    "10m": Timeframe.TEN_MINUTES,
    "1hour": Timeframe.ONE_HOUR,
    "1day": Timeframe.ONE_DAY,
}
DEFAULT_PAIRS = (
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "AUD/USD",
    "USD/CAD",
    "USD/CHF",
    "NZD/USD",
    "EUR/JPY",
    "GBP/JPY",
)
DEFAULT_HORIZONS = (1, 2, 3, 6)
STATE_LOOKBACK = 20
MAX_PROVIDER_BATCH_DAYS = 7


def _bar(bid: MarketBar, ask: MarketBar) -> Bar:
    if bid.timestamp != ask.timestamp:
        raise ValueError("BID/ASK timestamps must match")
    return Bar(
        timestamp=bid.timestamp,
        bid_open=float(bid.open),
        bid_high=float(bid.high),
        bid_low=float(bid.low),
        bid_close=float(bid.close),
        ask_open=float(ask.open),
        ask_high=float(ask.high),
        ask_low=float(ask.low),
        ask_close=float(ask.close),
        spread_open=float(ask.open - bid.open),
        spread_high=None,
        spread_low=None,
        spread_close=float(ask.close - bid.close),
    )


def _merge(bid: tuple[MarketBar, ...], ask: tuple[MarketBar, ...]) -> list[Bar]:
    bid_by_time = {item.timestamp: item for item in bid}
    ask_by_time = {item.timestamp: item for item in ask}
    if set(bid_by_time) != set(ask_by_time):
        raise ValueError("BID/ASK timestamp sets differ")
    return [_bar(bid_by_time[ts], ask_by_time[ts]) for ts in sorted(bid_by_time)]


def _volatility_z(state: State, history: list[State]) -> float:
    values: list[float] = []
    for item in history:
        value = item.features.get("volatility")
        if isinstance(value, (int, float)):
            values.append(float(value))
    if len(values) < 2:
        return 0.0
    average = mean(values)
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    std = variance**0.5
    current = float(state.features.get("volatility") or 0.0)
    return 0.0 if std == 0 else (current - average) / std


def _calibration(
    predicted: list[float], realized: list[bool]
) -> dict[str, float | int | None]:
    if not predicted:
        return {"n": 0, "brier": None, "predicted_rate": None, "realized_rate": None}
    outcomes = [1.0 if value else 0.0 for value in realized]
    brier = sum(
        (probability - outcome) ** 2
        for probability, outcome in zip(predicted, outcomes, strict=True)
    ) / len(outcomes)
    return {
        "n": len(predicted),
        "brier": brier,
        "predicted_rate": mean(predicted),
        "realized_rate": mean(outcomes),
    }


def _sequence_report(
    values: list[float],
    predicted: list[float],
    realized: list[bool],
    mfe: list[float],
    mae: list[float],
) -> dict[str, object]:
    return {
        "targets": len(values),
        "expectancy": expectancy(values),
        "max_drawdown": max_drawdown(values),
        "mfe_mean": mean(mfe) if mfe else None,
        "mae_mean": mean(mae) if mae else None,
        "probability_calibration": _calibration(predicted, realized),
    }


def analyze_pair(
    provider: DukascopyProvider,
    pair: str,
    instrument_id: int,
    start: datetime,
    end: datetime,
    timeframe: Timeframe,
    sample_stride: int,
    history_states: int,
    horizons: tuple[int, ...],
    max_days_per_batch: int,
    costs: ExecutionAssumptions,
) -> tuple[dict[str, object], list[tuple[datetime, float]]]:
    if max_days_per_batch <= 0 or max_days_per_batch > MAX_PROVIDER_BATCH_DAYS:
        raise ValueError(f"max_days_per_batch must be between 1 and {MAX_PROVIDER_BATCH_DAYS}")
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("horizons must contain positive integers")
    if sample_stride < max(horizons):
        raise ValueError("sample_stride must be at least max(horizons)")

    bars: list[Bar] = []
    for bid, ask in iter_bid_ask_batches(
        provider,
        instrument_id,
        timeframe,
        start,
        end,
        max_days_per_batch,
    ):
        bars.extend(_merge(bid, ask))

    minimum_bars = STATE_LOOKBACK + history_states + max(horizons) + 10
    if len(bars) < minimum_bars:
        raise ValueError(f"insufficient bars for {pair}: {len(bars)} < {minimum_bars}")
    for previous, current in zip(bars[:-1], bars[1:], strict=True):
        if current.timestamp <= previous.timestamp:
            raise ValueError("empirical bars must be strictly time ordered")

    states = [
        state_from_bar_window(bars, index, STATE_LOOKBACK)
        for index in range(STATE_LOOKBACK, len(bars))
    ]
    state_index = {state.timestamp: index + STATE_LOOKBACK for index, state in enumerate(states)}

    actual: dict[int, list[float]] = defaultdict(list)
    mfe: dict[int, list[float]] = defaultdict(list)
    mae: dict[int, list[float]] = defaultdict(list)
    predicted: dict[int, list[float]] = defaultdict(list)
    positive: dict[int, list[bool]] = defaultdict(list)
    target_times: dict[int, list[datetime]] = defaultdict(list)
    conditional: dict[int, list[float]] = defaultdict(list)
    grouped: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    analogue_future_rejections = 0
    spread_rejections = 0

    for position in range(history_states, len(states), sample_stride):
        target = states[position]
        target_index = state_index[target.timestamp]
        history = states[position - history_states : position]
        spread = float(target.features.get("spread") or 0.0)
        try:
            validate_spread(spread, costs)
        except ValueError:
            spread_rejections += 1
            continue

        scaler = fit_scaler(history, DEFAULT_FEATURES)
        nearest = nearest_states(target, history, scaler, k=min(100, len(history)))
        neighbors: list[tuple[State, float]] = []
        for state, distance in nearest:
            state_index_value = state_index[state.timestamp]
            if costs.max_spread is not None and float(
                state.features.get("spread") or 0.0
            ) > costs.max_spread:
                continue
            if any(state_index_value + horizon > target_index for horizon in horizons):
                analogue_future_rejections += 1
                continue
            neighbors.append((state, distance))

        if not neighbors:
            continue

        direction = "long" if float(target.features.get("momentum") or 0.0) >= 0 else "short"
        session = session_label(target.timestamp)
        regime = classify_regime(
            float(target.features.get("trend") or 0.0),
            float(target.features.get("trend_strength") or 0.0),
            _volatility_z(target, history),
            int(target.features.get("breakout") or 0),
        )

        for horizon in horizons:
            evidence: list[float] = []
            for neighbor, _distance in neighbors:
                outcome = future_outcome(bars, state_index[neighbor.timestamp], horizon, direction)
                evidence.append(net_move(outcome.return_abs, costs))
            if not evidence:
                continue
            conditional[horizon].extend(evidence)
            if target_index + horizon >= len(bars):
                continue

            outcome = future_outcome(bars, target_index, horizon, direction)
            value = net_move(outcome.return_abs, costs)
            p_positive = sum(item > 0 for item in evidence) / len(evidence)
            actual[horizon].append(value)
            mfe[horizon].append(outcome.mfe_abs)
            mae[horizon].append(outcome.mae_abs)
            predicted[horizon].append(p_positive)
            positive[horizon].append(value > 0)
            target_times[horizon].append(target.timestamp)
            grouped[f"session:{session}"][horizon].append(value)
            grouped[f"regime:{regime}"][horizon].append(value)
            grouped[f"year:{target.timestamp.year}"][horizon].append(value)

    horizon_report: dict[str, object] = {}
    for horizon in horizons:
        horizon_report[str(horizon)] = {
            "conditional_analogue_distribution": probability_summary(conditional[horizon]),
            "sequential_out_of_sample": _sequence_report(
                actual[horizon],
                predicted[horizon],
                positive[horizon],
                mfe[horizon],
                mae[horizon],
            ),
            "average_analogue_count": (
                len(conditional[horizon]) / len(actual[horizon]) if actual[horizon] else None
            ),
        }

    fold_times = target_times[max(horizons)] if horizons else []
    folds = expanding_walk_forward(
        fold_times,
        initial_train=timedelta(days=365),
        test_window=timedelta(days=180),
        step=timedelta(days=180),
        purge=timedelta(days=max(horizons)),
    )

    grouped_report = {
        group: {
            str(horizon): expectancy(values)
            for horizon, values in sorted(horizon_values.items())
        }
        for group, horizon_values in sorted(grouped.items())
    }

    report: dict[str, object] = {
        "pair": pair,
        "instrument_id": instrument_id,
        "timeframe": timeframe.value,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bars": len(bars),
        "states": len(states),
        "history_states": history_states,
        "sample_stride": sample_stride,
        "spread_rejected_targets": spread_rejections,
        "analogue_future_rejections": analogue_future_rejections,
        "walk_forward_fold_count": len(folds),
        "execution_model": {
            "entry_exit": "LONG ASK->BID, SHORT BID->ASK",
            "spread": "embedded in executable BID/ASK prices",
            "slippage": costs.slippage,
            "commission": costs.commission,
            "max_spread": costs.max_spread,
        },
        "horizons": horizon_report,
        "grouped_sequential_results": grouped_report,
        "research_scope": "sequential historical prediction experiment; no parameter optimization or live execution",
        "empirical": True,
    }

    returns = [
        (current.timestamp, (current.bid_close / previous.bid_close) - 1.0)
        for previous, current in zip(bars[:-1], bars[1:], strict=True)
    ]
    return report, returns


def _correlation_matrix(
    pairs: tuple[str, ...], series: dict[str, list[tuple[datetime, float]]]
) -> dict[str, dict[str, float | None]]:
    returns_by_pair = {pair: dict(values) for pair, values in series.items()}
    timestamps = sorted({timestamp for values in series.values() for timestamp, _ in values})
    matrix: dict[str, dict[str, float | None]] = {}
    for first in pairs:
        matrix[first] = {}
        for second in pairs:
            aligned = [
                (returns_by_pair[first][timestamp], returns_by_pair[second][timestamp])
                for timestamp in timestamps
                if timestamp in returns_by_pair[first] and timestamp in returns_by_pair[second]
            ]
            if len(aligned) < 3:
                matrix[first][second] = None
                continue
            first_values = [x for x, _ in aligned]
            second_values = [y for _, y in aligned]
            first_mean = mean(first_values)
            second_mean = mean(second_values)
            first_variance = sum((x - first_mean) ** 2 for x in first_values)
            second_variance = sum((y - second_mean) ** 2 for y in second_values)
            denominator = (first_variance * second_variance) ** 0.5
            if denominator == 0:
                matrix[first][second] = None
                continue
            numerator = sum(
                (x - first_mean) * (y - second_mean) for x, y in aligned
            )
            matrix[first][second] = numerator / denominator
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage-safe sequential Dukascopy research")
    parser.add_argument("--start", default="2020-01-01T00:00:00+00:00")
    parser.add_argument(
        "--end",
        default=datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat(),
    )
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    parser.add_argument("--timeframe", choices=sorted(TIMEFRAMES), default="10m")
    parser.add_argument("--sample-stride", type=int, default=120)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--max-days-per-batch", type=int, default=7)
    parser.add_argument("--slippage", type=float, default=0.0)
    parser.add_argument("--commission", type=float, default=0.0)
    parser.add_argument("--max-spread", type=float, default=None)
    parser.add_argument("--output", default="artifacts/empirical_report.json")
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise SystemExit("start/end must be timezone-aware and start < end")

    pairs = tuple(item.strip() for item in args.pairs.split(",") if item.strip())
    horizons = DEFAULT_HORIZONS
    costs = ExecutionAssumptions(args.slippage, args.commission, args.max_spread)

    with DukascopyProvider() as provider:
        instruments = {instrument.name.upper(): instrument for instrument in provider.instruments()}
        reports: list[dict[str, object]] = []
        series: dict[str, list[tuple[datetime, float]]] = {}
        for pair in pairs:
            instrument = instruments.get(pair.upper())
            if instrument is None:
                raise SystemExit(f"Dukascopy instrument not found: {pair}")
            report, returns = analyze_pair(
                provider,
                pair,
                instrument.id,
                start,
                end,
                TIMEFRAMES[args.timeframe],
                args.sample_stride,
                args.history_states,
                horizons,
                args.max_days_per_batch,
                costs,
            )
            reports.append(report)
            series[pair] = returns

    payload = {
        "research_status": "EMPIRICAL_SEQUENTIAL_RUN_COMPLETED",
        "source": "Dukascopy REST historicalPrices",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pairs": reports,
        "cross_pair_return_correlation": _correlation_matrix(pairs, series),
        "empirical": True,
        "synthetic": False,
        "warning": "Research evidence only; no profitability guarantee and live execution remains disabled.",
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
