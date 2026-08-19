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
STATE_LOOKBACK = 20
MAX_PROVIDER_BATCH_DAYS = 7


def _bar(bid: MarketBar, ask: MarketBar) -> Bar:
    if bid.timestamp != ask.timestamp:
        raise ValueError("BID/ASK timestamps must match")
    return Bar(
        timestamp=bid.timestamp,
        bid_open=float(bid.open), bid_high=float(bid.high), bid_low=float(bid.low), bid_close=float(bid.close),
        ask_open=float(ask.open), ask_high=float(ask.high), ask_low=float(ask.low), ask_close=float(ask.close),
        spread_open=float(ask.open - bid.open), spread_high=None, spread_low=None,
        spread_close=float(ask.close - bid.close),
    )


def _merge(bid: tuple[MarketBar, ...], ask: tuple[MarketBar, ...]) -> list[Bar]:
    b = {x.timestamp: x for x in bid}
    a = {x.timestamp: x for x in ask}
    if set(b) != set(a):
        raise ValueError("BID/ASK timestamp sets differ")
    return [_bar(b[ts], a[ts]) for ts in sorted(b)]


def _vol_z(state: State, history: list[State]) -> float:
    xs = [float(s.features["volatility"]) for s in history if isinstance(s.features.get("volatility"), (int, float))]
    if len(xs) < 2:
        return 0.0
    mu = mean(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    sd = var**0.5
    return 0.0 if sd == 0 else (float(state.features.get("volatility") or 0.0) - mu) / sd


def _calibration(pred: list[float], realized: list[bool]) -> dict[str, float | int | None]:
    if not pred:
        return {"n": 0, "brier": None, "predicted_rate": None, "realized_rate": None}
    ys = [1.0 if x else 0.0 for x in realized]
    brier = sum((p - y) ** 2 for p, y in zip(pred, ys, strict=True)) / len(ys)
    return {"n": len(pred), "brier": brier, "predicted_rate": mean(pred), "realized_rate": mean(ys)}


def _sequence_report(values: list[float], pred: list[float], realized: list[bool], mfe: list[float], mae: list[float]) -> dict[str, object]:
    return {
        "targets": len(values),
        "expectancy": expectancy(values),
        "max_drawdown": max_drawdown(values),
        "mfe_mean": mean(mfe) if mfe else None,
        "mae_mean": mean(mae) if mae else None,
        "probability_calibration": _calibration(pred, realized),
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
) -> tuple[dict[str, object], dict[int, list[tuple[datetime, float]]]]:
    if max_days_per_batch > MAX_PROVIDER_BATCH_DAYS:
        raise ValueError(f"max_days_per_batch cannot exceed {MAX_PROVIDER_BATCH_DAYS}")
    if sample_stride < max(horizons):
        raise ValueError("sample_stride must be at least max(horizons)")

    bars: list[Bar] = []
    for bid, ask in iter_bid_ask_batches(provider, instrument_id, timeframe, start, end, max_days_per_batch):
        bars.extend(_merge(bid, ask))
    if len(bars) < STATE_LOOKBACK + history_states + max(horizons) + 10:
        raise ValueError(f"insufficient bars for {pair}: {len(bars)}")

    states = [state_from_bar_window(bars, i, STATE_LOOKBACK) for i in range(STATE_LOOKBACK, len(bars))]
    index = {s.timestamp: i + STATE_LOOKBACK for i, s in enumerate(states)}

    actual: dict[int, list[float]] = defaultdict(list)
    mfe: dict[int, list[float]] = defaultdict(list)
    mae: dict[int, list[float]] = defaultdict(list)
    predicted: dict[int, list[float]] = defaultdict(list)
    positive: dict[int, list[bool]] = defaultdict(list)
    target_times: dict[int, list[datetime]] = defaultdict(list)
    conditional: dict[int, list[float]] = defaultdict(list)
    grouped: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    corr_series: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    analogue_future_rejections = 0
    spread_rejections = 0

    for pos in range(history_states, len(states), sample_stride):
        target = states[pos]
        target_idx = index[target.timestamp]
        history = states[pos - history_states : pos]
        spread = float(target.features.get("spread") or 0.0)
        try:
            validate_spread(spread, costs)
        except ValueError:
            spread_rejections += 1
            continue
        scaler = fit_scaler(history, DEFAULT_FEATURES)
        neighbors_raw = nearest_states(target, history, scaler, k=min(100, len(history)))
        neighbors: list[tuple[State, float]] = []
        for state, distance in neighbors_raw:
            if costs.max_spread is not None and float(state.features.get("spread") or 0.0) > costs.max_spread:
                continue
            # For every analogue used for prediction, its full outcome must be known by T.
            if any(index[state.timestamp] + h > target_idx for h in horizons):
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
            _vol_z(target, history),
            int(target.features.get("breakout") or 0),
        )

        for h in horizons:
            evidence: list[float] = []
            for neighbor, _distance in neighbors:
                outcome = future_outcome(bars, index[neighbor.timestamp], h, direction)
                evidence.append(net_move(outcome.return_abs, costs))
            if not evidence:
                continue
            conditional[h].extend(evidence)
            if target_idx + h >= len(bars):
                continue
            outcome = future_outcome(bars, target_idx, h, direction)
            value = net_move(outcome.return_abs, costs)
            p_up = sum(x > 0 for x in evidence) / len(evidence)
            actual[h].append(value)
            mfe[h].append(outcome.mfe_abs)
            mae[h].append(outcome.mae_abs)
            predicted[h].append(p_up)
            positive[h].append(value > 0)
            target_times[h].append(target.timestamp)
            grouped[f"session:{session}"][h].append(value)
            grouped[f"regime:{regime}"][h].append(value)
            grouped[f"year:{target.timestamp.year}"][h].append(value)

    horizons_report: dict[str, object] = {}
    for h in horizons:
        horizons_report[str(h)] = {
            "conditional_analogue_distribution": probability_summary(conditional[h]),
            "sequential_out_of_sample": _sequence_report(actual[h], predicted[h], positive[h], mfe[h], mae[h]),
            "average_analogue_count": len(conditional[h]) / len(actual[h]) if actual[h] else None,
        }

    folds = expanding_walk_forward(
        target_times[max(horizons)] if horizons else [],
        initial_train=timedelta(days=365),
        test_window=timedelta(days=180),
        step=timedelta(days=180),
        purge=timedelta(days=max(horizons)),
    )
    grouped_report = {group: {str(h): expectancy(vals) for h, vals in sorted(by_h.items())} for group, by_h in sorted(grouped.items())}
    for bar_prev, bar_cur in zip(bars, bars[1:], strict=True):
        corr_series[1].append((bar_cur.timestamp, (bar_cur.bid_close / bar_prev.bid_close) - 1.0))

    report = {
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
        "horizons": horizons_report,
        "grouped_sequential_results": grouped_report,
        "research_scope": "sequential historical prediction experiment; no parameter optimization or live execution",
        "empirical": True,
    }
    return report, corr_series


def main() -> None:
    parser = argparse.ArgumentParser(description="Leakage-safe sequential Dukascopy research")
    parser.add_argument("--start", default="2020-01-01T00:00:00+00:00")
    parser.add_argument("--end", default=datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat())
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
    pairs = tuple(p.strip() for p in args.pairs.split(",") if p.strip())
    costs = ExecutionAssumptions(args.slippage, args.commission, args.max_spread)

    with DukascopyProvider() as provider:
        instruments = {instrument.name.upper(): instrument for instrument in provider.instruments()}
        reports: list[dict[str, object]] = []
        series: dict[str, list[tuple[datetime, float]]] = {}
        for pair in pairs:
            instrument = instruments.get(pair.upper())
            if instrument is None:
                raise SystemExit(f"Dukascopy instrument not found: {pair}")
            report, corr = analyze_pair(
                provider, pair, instrument.id, start, end, TIMEFRAMES[args.timeframe],
                args.sample_stride, args.history_states, DEFAULT_HORIZONS,
                args.max_days_per_batch, costs,
            )
            reports.append(report)
            series[pair] = corr[1]

    timestamps = sorted({ts for values in series.values() for ts, _ in values})
    returns_by_pair = {pair: dict(values) for pair, values in series.items()}
    correlation: dict[str, dict[str, float | None]] = {}
    for a in pairs:
        correlation[a] = {}
        for b in pairs:
            aligned = [(returns_by_pair[a][ts], returns_by_pair[b][ts]) for ts in timestamps if ts in returns_by_pair[a] and ts in returns_by_pair[b]]
            if len(aligned) < 3:
                correlation[a][b] = None
                continue
            xa = [x for x, _ in aligned]; xb = [y for _, y in aligned]
            ma = mean(xa); mb = mean(xb)
            va = sum((x - ma) ** 2 for x in xa); vb = sum((y - mb) ** 2 for y in xb)
            denom = (va * vb) ** 0.5
            correlation[a][b] = None if denom == 0 else sum((x - ma) * (y - mb) for x, y in aligned) / denom

    payload = {
        "research_status": "EMPIRICAL_SEQUENTIAL_RUN_COMPLETED",
        "source": "Dukascopy REST historicalPrices",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pairs": reports,
        "cross_pair_return_correlation": correlation,
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
