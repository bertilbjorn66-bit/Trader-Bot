from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

import research.currency_strength_confirmation as confirmation
import research.currency_strength_discovery as discovery

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _feed() -> discovery.Feed:
    timestamps = np.asarray(
        [int((BASE + timedelta(minutes=10 * index)).timestamp() * 1000) for index in range(32)],
        dtype=np.int64,
    )
    bid_close = np.asarray([100.0 + index for index in range(32)], dtype=np.float64)
    ask_close = bid_close + 0.2
    return discovery.Feed(
        pair="USD/JPY",
        timestamps=timestamps,
        bid_open=bid_close - 0.1,
        ask_open=bid_close + 0.1,
        bid_close=bid_close,
        ask_close=ask_close,
        mid_close=(bid_close + ask_close) / 2.0,
        rolling_vol=np.ones(32, dtype=np.float64),
        timestamp_index={int(value): index for index, value in enumerate(timestamps)},
        quality={},
    )


def test_confirmation_contract_is_frozen() -> None:
    assert confirmation.CONFIRMATION_CONTRACT_VERSION == "v1-currency-strength-confirmation"


def test_block_bootstrap_operates_on_timestamp_means() -> None:
    means = {index: float(index + 1) for index in range(12)}
    lower = confirmation._bootstrap_block_lower(means, reps=200, seed=7)
    assert np.isfinite(lower)


def test_confirmation_positions_exclude_pre_cutoff_timestamps() -> None:
    feed = _feed()
    cutoff = int((BASE + timedelta(minutes=80)).timestamp() * 1000)
    positions, timestamps = confirmation._confirmation_positions({"USD/JPY": feed}, cutoff)
    assert all(ts >= cutoff for ts in timestamps)
    assert positions["USD/JPY"]
