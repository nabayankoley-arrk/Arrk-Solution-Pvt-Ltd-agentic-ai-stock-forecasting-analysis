"""compute_trend — signal node (runs in parallel with the other compute_*
nodes after fetch_price_history).

Calculates SMA_20/SMA_50/SMA_200 and classifies the trend by whether the
current close and the available moving averages are in strict descending
order (current > short > medium > long -> bullish), strict ascending order
(-> bearish), or neither (-> neutral). Moving averages that can't be
computed yet (e.g. SMA_200 early in a ticker's history) are simply left
out of the ordering check rather than failing the node.
"""

from ..config import LONG_MA_PERIOD, MEDIUM_MA_PERIOD, SHORT_MA_PERIOD
from ._indicators import sma


def compute_trend(state):
    history = state.get("price_history") or []
    closes = [row["close_price"] for row in history]
    current_price = closes[-1] if closes else None

    sma_short = sma(closes, SHORT_MA_PERIOD)
    sma_medium = sma(closes, MEDIUM_MA_PERIOD)
    sma_long = sma(closes, LONG_MA_PERIOD)

    values = [current_price] + [v for v in (sma_short, sma_medium, sma_long) if v is not None]

    if current_price is None or len(values) < 2:
        classification = "neutral"
    elif all(values[i] > values[i + 1] for i in range(len(values) - 1)):
        classification = "bullish"
    elif all(values[i] < values[i + 1] for i in range(len(values) - 1)):
        classification = "bearish"
    else:
        classification = "neutral"

    detail = {
        "current_price": _round(current_price),
        "sma_20": _round(sma_short),
        "sma_50": _round(sma_medium),
        "sma_200": _round(sma_long),
    }
    return {"trend": {"classification": classification, "detail": detail}}


def _round(value):
    return round(value, 4) if value is not None else None
