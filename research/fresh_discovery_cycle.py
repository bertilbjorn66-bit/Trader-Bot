from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import research.enriched_conditional_experiment as experiment
from .datafeed_empirical import PAIR_TO_SYMBOL, load_feed_bars
from .execution import ExecutionAssumptions
from .sequential_empirical import DEFAULT_HORIZONS


AGREEMENT_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75)
DISTANCE_GRID: tuple[float | None, ...] = (None, 0.5, 1.0, 1.5, 2.0)
REGIMES = (
    "regime:breakout_up",
    "regime:breakout_down",
    "regime:high_vol_trend_up",
    "regime:high_vol_trend_down",
    "regime:high_volatility_range",
    "regime:trend_up",
    "regime:trend_down",
    "regime:range_low_vol",
    "regime:range_normal",
)
SESSIONS = ("asia", "london", "new_york", "overlap")
PAIRSETS = ("all", "JPY")