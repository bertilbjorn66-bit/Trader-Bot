from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import fmean, pstdev
from typing import Sequence

from .models import MarketBar, OfferSide


@dataclass(frozen=True)
class MarketState:
    timestamp: datetime
    instrument: int
    timeframe: str
    last_bid: Decimal
    last_ask: Decimal
    spread: Decimal
    return_5: float
    return_20: float
    range_20: Decimal
    range_60: Decimal
    volatility_20: float
    volatility_60: float
    trend_fast_slow: float
    session_utc: str


def _returns(closes: Sequence[Decimal]) -> list[float]:
    return [float((cur - prev) / prev) if prev else 0.0 for prev, cur in zip(closes, closes[1:])]


def build_state(bid: Sequence[MarketBar], ask: Sequence[MarketBar]) -> MarketState:
    if len(bid) != len(ask) or len(bid) < 61:
        raise ValueError("At least 61 aligned BID/ASK bars are required")
    if any(b.offer_side != OfferSide.BID for b in bid) or any(a.offer_side != OfferSide.ASK for a in ask):
        raise ValueError("BID/ASK side mismatch")
    if [b.timestamp for b in bid] != [a.timestamp for a in ask]:
        raise ValueError("BID/ASK timestamps must align")

    closes = [b.close for b in bid]
    rets = _returns(closes)
    last_bid, last_ask = bid[-1].close, ask[-1].close
    sma_fast = fmean(closes[-20:])
    sma_slow = fmean(closes[-60:])
    ts = bid[-1].timestamp
    hour = ts.hour
    session = "asia" if hour < 7 else "london" if hour < 13 else "new_york" if hour < 21 else "rollover"

    return MarketState(
        timestamp=ts,
        instrument=bid[-1].instrument,
        timeframe=bid[-1].timeframe.value,
        last_bid=last_bid,
        last_ask=last_ask,
        spread=last_ask - last_bid,
        return_5=float((closes[-1] - closes[-6]) / closes[-6]),
        return_20=float((closes[-1] - closes[-21]) / closes[-21]),
        range_20=max(x.high for x in bid[-20:]) - min(x.low for x in bid[-20:]),
        range_60=max(x.high for x in bid[-60:]) - min(x.low for x in bid[-60:]),
        volatility_20=pstdev(rets[-20:]) if len(rets) >= 20 else 0.0,
        volatility_60=pstdev(rets[-60:]) if len(rets) >= 60 else 0.0,
        trend_fast_slow=float((sma_fast - sma_slow) / sma_slow) if sma_slow else 0.0,
        session_utc=session,
    )
