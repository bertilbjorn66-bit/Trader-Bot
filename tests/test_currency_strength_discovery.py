from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from research.currency_strength_discovery import (
    CONTRACT_VERSION,
    ENTRY_DELAY_BARS,
    Feed,
    Trade,
    _candidate_metrics,
    _currency_components,
    _rolling_std,
    _trade_for_signal,
    assign_global_split,
    candidate_fingerprint,
    family_hypotheses,
    holm_adjust,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _feed() -> Feed:
    timestamps = np.asarray(
        [int((BASE + timedelta(minutes=10 * index)).timestamp() * 1000) for index in range(8)],
        dtype=np.int64,
    )
    bid_close = np.asarray([100.0 + index for index in range(8)], dtype=np.float64)
    ask_close = bid_close + 0.2
    return Feed(
        pair="USD/JPY",
        timestamps=timestamps,
        bid_open=bid_close - 0.1,
        ask_open=bid_close + 0.1,
        bid_close=bid_close,
        ask_close=ask_close,
        mid_close=(bid_close + ask_close) / 2.0,
        rolling_vol=np.ones(8, dtype=np.float64),
        timestamp_index={int(value): index for index, value in enumerate(timestamps)},
        quality={},
    )


def test_family_size_is_frozen() -> None:
    assert len(family_hypotheses()) == 144


def test_discovery_stride_is_frozen() -> None:
    from research.currency_strength_discovery import FIXED_SAMPLE_STRIDE

    assert FIXED_SAMPLE_STRIDE == 60


def test_entry_model_is_next_open_not_signal_close() -> None:
    assert ENTRY_DELAY_BARS == 1


def test_candidate_fingerprint_binds_every_search_dimension() -> None:
    base = family_hypotheses()[0]
    assert candidate_fingerprint(base) != candidate_fingerprint({**base, "threshold": 1.0})
    assert candidate_fingerprint(base) != candidate_fingerprint({**base, "lookback": 48})
    assert CONTRACT_VERSION.startswith("v3-")


def test_candidate_record_contains_contract_and_fingerprint_without_trades() -> None:
    result = _candidate_metrics(
        {"USD/JPY": _feed()},
        {"USD/JPY": []},
        {},
        int((BASE + timedelta(days=1)).timestamp() * 1000),
        family_hypotheses()[0],
    )
    assert result["candidate"]["contract_version"] == CONTRACT_VERSION
    assert result["candidate_fingerprint"] == candidate_fingerprint(result["candidate"])


def test_rolling_std_requires_complete_windows() -> None:
    values = np.arange(10, dtype=np.float64)
    result = _rolling_std(values, 4)
    assert np.isnan(result[:3]).all()
    assert np.isfinite(result[3:]).all()


def test_currency_components_require_complete_nine_pair_cross_section() -> None:
    base_feed = _feed()
    partial = {"USD/JPY": base_feed}
    timestamp = int(base_feed.timestamps[-1])
    raw, normalized, dispersion = _currency_components(partial, timestamp, 6)
    assert raw == {}
    assert normalized == {}
    assert np.isnan(dispersion)

    full = {
        pair: Feed(
            pair=pair,
            timestamps=base_feed.timestamps,
            bid_open=base_feed.bid_open,
            ask_open=base_feed.ask_open,
            bid_close=base_feed.bid_close,
            ask_close=base_feed.ask_close,
            mid_close=base_feed.mid_close,
            rolling_vol=base_feed.rolling_vol,
            timestamp_index=base_feed.timestamp_index,
            quality={},
        )
        for pair in (
            "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
            "USD/CHF", "NZD/USD", "EUR/JPY", "GBP/JPY",
        )
    }
    raw, normalized, dispersion = _currency_components(full, timestamp, 6)
    assert raw
    assert normalized
    assert np.isfinite(dispersion)


def test_trade_uses_exact_bid_ask_directional_pnl() -> None:
    feed = _feed()
    trade_long = _trade_for_signal(
        feed, position=2, horizon=3, mode="raw_strength",
        orientation="momentum", threshold=0.5, signal=1.0, lookback=6,
    )
    assert trade_long is not None
    assert ENTRY_DELAY_BARS == 1
    assert trade_long.horizon == 3
    assert trade_long.outcome_pips == (feed.bid_close[5] - feed.ask_open[3]) / 0.01
    assert trade_long.target_end_ms == int(feed.timestamps[5])

    trade_short = _trade_for_signal(
        feed, position=2, horizon=3, mode="raw_strength",
        orientation="momentum", threshold=0.5, signal=-1.0, lookback=6,
    )
    assert trade_short is not None
    assert trade_short.outcome_pips == (feed.bid_open[3] - feed.ask_close[5]) / 0.01


def test_global_split_uses_target_end_time() -> None:
    trades = [
        Trade(
            timestamp_ms=int((BASE + timedelta(minutes=10 * index)).timestamp() * 1000),
            target_end_ms=int((BASE + timedelta(minutes=10 * (index + 1))).timestamp() * 1000),
            pair="USD/JPY",
            lookback=6,
            horizon=3,
            mode="raw_strength",
            orientation="momentum",
            threshold=0.5,
            signal=1.0,
            outcome_pips=1.0,
        )
        for index in range(10)
    ]
    split, cutoff = assign_global_split(trades)
    assert cutoff is not None
    assert all(
        trade.split == ("discovery" if trade.target_end_ms < cutoff else "confirmation")
        for trade in split
    )


def test_cluster_bootstrap_uses_timestamp_means() -> None:
    from research.currency_strength_discovery import _clustered_block_lower

    timestamp_means = {index: float(index + 1) for index in range(12)}
    lower = _clustered_block_lower(timestamp_means, reps=200, seed=7)
    assert np.isfinite(lower)


def test_holm_adjustment_is_monotone() -> None:
    results = [
        {"hac_one_sided_pvalue": 0.001, "passes_pre_holm": True},
        {"hac_one_sided_pvalue": 0.02, "passes_pre_holm": True},
        {"hac_one_sided_pvalue": 0.20, "passes_pre_holm": True},
    ]
    adjusted = holm_adjust(results)
    values = [float(item["holm_adjusted_pvalue"]) for item in adjusted]
    assert values == sorted(values)
    assert all("passes_familywise" in item for item in adjusted)
