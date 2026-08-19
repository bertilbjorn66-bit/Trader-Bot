from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class Bar:
    timestamp: datetime
    bid_open: float
    bid_high: float
    bid_low: float
    bid_close: float
    ask_open: float
    ask_high: float
    ask_low: float
    ask_close: float
    spread_open: float | None = None
    spread_high: float | None = None
    spread_low: float | None = None
    spread_close: float | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Bar timestamp must be timezone-aware")
        bid = (self.bid_open, self.bid_high, self.bid_low, self.bid_close)
        ask = (self.ask_open, self.ask_high, self.ask_low, self.ask_close)
        if not all(isfinite(v) and v > 0 for v in bid + ask):
            raise ValueError("Bar prices must be finite and positive")
        if self.bid_high < max(self.bid_open, self.bid_close) or self.bid_low > min(self.bid_open, self.bid_close):
            raise ValueError("Invalid BID OHLC")
        if self.ask_high < max(self.ask_open, self.ask_close) or self.ask_low > min(self.ask_open, self.ask_close):
            raise ValueError("Invalid ASK OHLC")
        if self.ask_low < self.bid_low or self.ask_high < self.bid_high:
            # Not necessarily invalid for independently sampled OHLC bars; only the
            # close/open cross-side relationship is enforced below.
            pass
        if self.ask_close < self.bid_close or self.ask_open < self.bid_open:
            raise ValueError("ASK must be >= BID at open and close")

    @property
    def spread(self) -> float:
        if self.spread_close is not None:
            return self.spread_close
        return self.ask_close - self.bid_close


@dataclass(frozen=True, slots=True)
class State:
    timestamp: datetime
    features: dict[str, float | str | int | None]


@dataclass(frozen=True, slots=True)
class Outcome:
    timestamp: datetime
    horizon_bars: int
    direction: str
    entry: float
    exit: float
    return_abs: float
    mfe_abs: float
    mae_abs: float
    hit_target_before_stop: bool | None


@dataclass(frozen=True, slots=True)
class ValidationFold:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(slots=True)
class ResearchResult:
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    findings: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    empirical: bool = False
