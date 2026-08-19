from __future__ import annotations


def classify_regime(trend: float, trend_strength: float, volatility_z: float, breakout: int) -> str:
    if breakout > 0:
        return "breakout_up"
    if breakout < 0:
        return "breakout_down"
    if volatility_z >= 1.0:
        if trend > 0 and trend_strength > 0.5:
            return "high_vol_trend_up"
        if trend < 0 and trend_strength > 0.5:
            return "high_vol_trend_down"
        return "high_volatility_range"
    if trend_strength >= 0.5:
        return "trend_up" if trend > 0 else "trend_down"
    return "range_low_vol" if volatility_z <= -1.0 else "range_normal"
