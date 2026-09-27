"""compute_volatility — signal node (runs in parallel with the other
compute_* nodes after fetch_price_history).

Calculates ATR_14 and Bollinger Bands(20, 2), then classifies volatility
as low/medium/high by comparing ATR as a percentage of the current close
against ATR_PERCENT_LOW_THRESHOLD/ATR_PERCENT_HIGH_THRESHOLD. Bollinger
band width is reported alongside for transparency but isn't itself part
of the classification -- ATR is the more standard single volatility gauge
and the specification doesn't define how the two would be combined.

Also reports `daily_return_std_pct`: the standard deviation of daily log
returns over the last RETURN_VOLATILITY_WINDOW sessions, in percent. It is
not part of the classification; the orchestrator's price forecast is built on
it (agents/orchestrator/forecast_price_range.py), since ATR measures the
intraday high-low range and overstates how far the close moves day to day.
"""

import math

from ..config import (
    ATR_PERCENT_HIGH_THRESHOLD,
    ATR_PERCENT_LOW_THRESHOLD,
    ATR_PERIOD,
    BOLLINGER_PERIOD,
    BOLLINGER_STD_DEV,
    RETURN_VOLATILITY_WINDOW,
)
from ._indicators import atr as compute_atr
from ._indicators import bollinger_bands


def compute_volatility(state):
    history = state.get("price_history") or []
    highs = [row["high_price"] for row in history]
    lows = [row["low_price"] for row in history]
    closes = [row["close_price"] for row in history]
    current_price = closes[-1] if closes else None

    atr_value = compute_atr(highs, lows, closes, ATR_PERIOD)
    bands = bollinger_bands(closes, BOLLINGER_PERIOD, BOLLINGER_STD_DEV)

    if atr_value is None or not current_price:
        return {
            "volatility": {
                "classification": None,
                "detail": {"reason": "insufficient price history for ATR"},
            }
        }

    atr_pct = atr_value / current_price * 100
    return_std_pct = _daily_return_std_pct(closes)
    if atr_pct < ATR_PERCENT_LOW_THRESHOLD:
        classification = "low"
    elif atr_pct > ATR_PERCENT_HIGH_THRESHOLD:
        classification = "high"
    else:
        classification = "medium"

    detail = {
        "atr": _round(atr_value),
        "atr_pct": _round(atr_pct),
        "bollinger_upper": _round(bands["upper"]) if bands else None,
        "bollinger_middle": _round(bands["middle"]) if bands else None,
        "bollinger_lower": _round(bands["lower"]) if bands else None,
        "bollinger_width_pct": _round(bands["width_pct"]) if bands else None,
        "daily_return_std_pct": _round(return_std_pct),
    }
    return {"volatility": {"classification": classification, "detail": detail}}


def _daily_return_std_pct(closes):
    """Sample standard deviation of daily log returns over the last
    RETURN_VOLATILITY_WINDOW sessions, in percent; None with too little history."""
    window = [c for c in closes[-(RETURN_VOLATILITY_WINDOW + 1):] if c and c > 0]
    returns = [math.log(b / a) for a, b in zip(window, window[1:])]
    if len(returns) < 20:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * 100


def _round(value):
    return round(value, 4) if value is not None else None
