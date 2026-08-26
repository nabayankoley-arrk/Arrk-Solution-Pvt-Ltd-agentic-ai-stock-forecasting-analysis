"""compute_momentum — signal node (runs in parallel with the other
compute_* nodes after fetch_price_history).

Calculates RSI_14 and MACD(12,26,9), tags the RSI as overbought/oversold/
neutral, and classifies momentum as bullish (RSI > 50 and MACD histogram
> 0), bearish (RSI < 50 and MACD histogram < 0), or neutral otherwise.
Whether momentum confirms or contradicts the trend is left to
aggregate_technical_signal, which sees both classifications.
"""

from ..config import MACD_FAST, MACD_SIGNAL, MACD_SLOW, RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_PERIOD
from ._indicators import macd as compute_macd
from ._indicators import rsi as compute_rsi


def compute_momentum(state):
    history = state.get("price_history") or []
    closes = [row["close_price"] for row in history]

    rsi_value = compute_rsi(closes, RSI_PERIOD)
    macd_result = compute_macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    histogram = macd_result["histogram"]

    if rsi_value is None or histogram is None:
        return {
            "momentum": {
                "classification": None,
                "detail": {
                    "reason": "insufficient price history for RSI/MACD",
                    "rsi": _round(rsi_value),
                },
            }
        }

    if rsi_value >= RSI_OVERBOUGHT:
        rsi_state = "overbought"
    elif rsi_value <= RSI_OVERSOLD:
        rsi_state = "oversold"
    else:
        rsi_state = "neutral"

    if rsi_value > 50 and histogram > 0:
        classification = "bullish"
    elif rsi_value < 50 and histogram < 0:
        classification = "bearish"
    else:
        classification = "neutral"

    detail = {
        "rsi": _round(rsi_value),
        "rsi_state": rsi_state,
        "macd_line": _round(macd_result["macd_line"]),
        "macd_signal": _round(macd_result["signal_line"]),
        "macd_histogram": _round(histogram),
    }
    return {"momentum": {"classification": classification, "detail": detail}}


def _round(value):
    return round(value, 4) if value is not None else None
