from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from trader_bot.models import MarketBar, Timeframe
from trader_bot.providers.dukascopy import DukascopyProvider

from .historical_scan import iter_bid_ask_batches
from .outcomes import future_outcome
from .pipeline import state_from_bar_window
from .statistics import expectancy, max_drawdown, probability_summary
from .types import Bar, State
from .validation import ensure_time_order
from .similarity import DEFAULT_FEATURES, fit_scaler, nearest_states

TIMEFRAMES = {
    "1min": Timeframe.ONE_MINUTE,
    "10m": Timeframe.TEN_MINUTES,
    "1hour": Timeframe.ONE_HOUR,
    "1day": Timeframe.ONE_DAY,
}

DEFAULT_PAIRS = ("EUR/USD",)
DEFAULT_HORIZONS = (1, 2, 3, 6)


def _to_bar(timestamp: datetime, bid: MarketBar, ask: MarketBar) -> Bar:
    return Bar(
        timestamp=timestamp,
        bid_open=float(bid.open),
        bid_high=float(bid.high),
        bid_low=float(bid.low),
        bid_close=float(bid.close),
        ask_open=float(ask.open),
        ask_high=float(ask.high),
        ask_low=float(ask.low),
        ask_close=float(ask.close),
        spread_open=float(ask.open - bid.open),
        spread_high=float(ask.high - bid.high),
        spread_low=float(ask.low - bid.low),
        spread_close=float(ask.close - bid.close),
    )


def _merge_batches(
    bid_bars: tuple[MarketBar, ...],
    ask_bars: tuple[MarketBar, ...],
) -> list[Bar]:
    bid_by_time = {bar.timestamp: bar for bar in bid_bars}
    ask_by_time = {bar.timestamp: bar for bar in ask_bars}
    if set(bid_by_time) != set(ask_by_time):
        raise ValueError("BID/ASK timestamps are not identical")
    bars = [_to_bar(ts, bid_by_time[ts], ask_by_time[ts]) for ts in sorted(bid_by_time)]
    ensure_time_order(bars)
    return bars


def _states_for_bars(bars: list[Bar], lookback: int = 20) -> list[State]:
    return [state_from_bar_window(bars, i, lookback) for i in range(lookback, len(bars))]


def analyze_pair(
    provider: DukascopyProvider,
    pair_name: str,
    instrument_id: int,
    start: datetime,
    end: datetime,
    timeframe: Timeframe,
    sample_stride: int,
    history_states: int,
    horizons: tuple[int, ...],
    max_days_per_batch: int,
) -> dict[str, object]:
    bars: list[Bar] = []
    for bid, ask in iter_bid_ask_batches(
        provider,
        instrument_id,
        timeframe,
        start,
        end,
        max_days_per_batch=max_days_per_batch,
    ):
        bars.extend(_merge_batches(bid, ask))

    if len(bars) < 100:
        raise ValueError(f"insufficient bars for {pair_name}: {len(bars)}")

    states = _states_for_bars(bars)
    state_index = {state.timestamp: i + 20 for i, state in enumerate(states)}
    results: dict[int, list[float]] = defaultdict(list)
    mfes: dict[int, list[float]] = defaultdict(list)
    maes: dict[int, list[float]] = defaultdict(list)
    distances: list[float] = []
    sampled = 0

    for pos in range(history_states, len(states), sample_stride):
        target = states[pos]
        current_index = state_index[target.timestamp]
        history = states[max(0, pos - history_states):pos]
        if len(history) < 100:
            continue
        scaler = fit_scaler(history, DEFAULT_FEATURES)
        neighbors = nearest_states(target, history, scaler, k=min(100, len(history)))
        if not neighbors:
            continue
        direction = "long" if float(target.features.get("momentum") or 0.0) >= 0 else "short"
        sampled += 1
        for _, distance in neighbors:
            distances.append(distance)

        for horizon in horizons:
            horizon_outcomes: list[float] = []
            horizon_mfe: list[float] = []
            horizon_mae: list[float] = []
            for neighbor, _distance in neighbors:
                idx = state_index[neighbor.timestamp]
                if idx + horizon >= len(bars):
                    continue
                outcome = future_outcome(bars, idx, horizon, direction)
                horizon_outcomes.append(outcome.return_abs)
                horizon_mfe.append(outcome.mfe_abs)
                horizon_mae.append(outcome.mae_abs)
            results[horizon].extend(horizon_outcomes)
            mfes[horizon].extend(horizon_mfe)
            maes[horizon].extend(horizon_mae)

    report_horizons: dict[str, object] = {}
    for horizon in horizons:
        vals = results[horizon]
        report_horizons[str(horizon)] = {
            "bars_forward": horizon,
            "observations": len(vals),
            "probability": probability_summary(vals),
            "expectancy": expectancy(vals),
            "max_drawdown": max_drawdown(vals),
            "mfe_mean": sum(mfes[horizon]) / len(mfes[horizon]) if mfes[horizon] else None,
            "mae_mean": sum(maes[horizon]) / len(maes[horizon]) if maes[horizon] else None,
        }

    return {
        "pair": pair_name,
        "instrument_id": instrument_id,
        "timeframe": timeframe.value,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bars": len(bars),
        "states": len(states),
        "sample_stride": sample_stride,
        "history_states": history_states,
        "sampled_targets": sampled,
        "mean_neighbor_distance": sum(distances) / len(distances) if distances else None,
        "horizons": report_horizons,
        "empirical": True,
        "warning": "Empirical historical research only; not evidence of future profitability.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run empirical Dukascopy research without a raw CSV archive.")
    parser.add_argument("--start", default="2020-01-01T00:00:00+00:00")
    parser.add_argument("--end", default=datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat())
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    parser.add_argument("--timeframe", choices=sorted(TIMEFRAMES), default="10m")
    parser.add_argument("--sample-stride", type=int, default=120)
    parser.add_argument("--history-states", type=int, default=10000)
    parser.add_argument("--max-days-per-batch", type=int, default=30)
    parser.add_argument("--horizons", default=",".join(map(str, DEFAULT_HORIZONS)))
    parser.add_argument("--output", default="artifacts/empirical_report.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if start.tzinfo is None or end.tzinfo is None:
        raise SystemExit("start/end must include timezone offsets")
    if start >= end:
        raise SystemExit("start must be before end")
    timeframe = TIMEFRAMES[args.timeframe]
    pairs = tuple(p.strip() for p in args.pairs.split(",") if p.strip())
    horizons = tuple(int(x) for x in args.horizons.split(",") if x.strip())
    if not horizons or any(x <= 0 for x in horizons):
        raise SystemExit("horizons must contain positive integers")

    with DukascopyProvider() as provider:
        instruments = {instrument.name.upper(): instrument for instrument in provider.instruments()}
        reports: list[dict[str, object]] = []
        for pair in pairs:
            instrument = instruments.get(pair.upper())
            if instrument is None:
                raise SystemExit(f"Dukascopy instrument not found: {pair}")
            reports.append(
                analyze_pair(
                    provider,
                    pair,
                    instrument.id,
                    start,
                    end,
                    timeframe,
                    args.sample_stride,
                    args.history_states,
                    horizons,
                    args.max_days_per_batch,
                )
            )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "research_status": "EMPIRICAL_RUN_COMPLETED",
        "source": "Dukascopy REST historicalPrices",
        "source_note": "BID and ASK were retrieved separately and aligned by timestamp.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pairs": reports,
        "empirical": True,
        "synthetic": False,
    }
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
