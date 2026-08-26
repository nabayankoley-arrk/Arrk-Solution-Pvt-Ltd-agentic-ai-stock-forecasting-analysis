"""detect_candlestick_pattern — signal node.

Scans the last 5 candles for four classic patterns -- bullish/bearish
engulfing (2-candle) and hammer/shooting star (1-candle) -- using
SHADOW_TOLERANCE_PERCENT to allow some flexibility around the textbook
shadow/body ratios. Scans most-recent-candle-first and, at a given
candle, checks the 2-candle pattern before the 1-candle one, so the
"strongest or most recent matching pattern" (per the specification) is
whichever is found first under that ordering.

Pure single-candle patterns with no directional bias (e.g. Doji) are
intentionally not detected here -- the specification calls for "bullish
or bearish reversal/continuation patterns", and a directionless pattern
has nothing for check_prior_trend_alignment to validate.
"""

from ..config import SHADOW_TOLERANCE_PERCENT

RECENT_CANDLES = 5
_SMALL_BODY_RATIO = 0.35


def detect_candlestick_pattern(state):
    history = state.get("price_history") or []
    recent = history[-RECENT_CANDLES:]

    for i in range(len(recent) - 1, -1, -1):
        candle = recent[i]
        if i > 0:
            prev = recent[i - 1]
            if _is_bullish_engulfing(prev, candle):
                return _result("bullish_engulfing", "bullish", prev, candle)
            if _is_bearish_engulfing(prev, candle):
                return _result("bearish_engulfing", "bearish", prev, candle)
        if _is_hammer(candle):
            return _result("hammer", "bullish", candle, candle)
        if _is_shooting_star(candle):
            return _result("shooting_star", "bearish", candle, candle)

    return {"candlestick_pattern": None, "pattern_direction": None}


def _body(row):
    return abs(row["close_price"] - row["open_price"])


def _candle_range(row):
    return row["high_price"] - row["low_price"]


def _is_bullish_engulfing(prev, curr):
    prev_bearish = prev["close_price"] < prev["open_price"]
    curr_bullish = curr["close_price"] > curr["open_price"]
    engulfs = curr["open_price"] <= prev["close_price"] and curr["close_price"] >= prev["open_price"]
    return prev_bearish and curr_bullish and engulfs


def _is_bearish_engulfing(prev, curr):
    prev_bullish = prev["close_price"] > prev["open_price"]
    curr_bearish = curr["close_price"] < curr["open_price"]
    engulfs = curr["open_price"] >= prev["close_price"] and curr["close_price"] <= prev["open_price"]
    return prev_bullish and curr_bearish and engulfs


def _is_hammer(row):
    body = _body(row)
    candle_range = _candle_range(row)
    if candle_range == 0:
        return False

    lower_shadow = min(row["open_price"], row["close_price"]) - row["low_price"]
    upper_shadow = row["high_price"] - max(row["open_price"], row["close_price"])
    tolerance = SHADOW_TOLERANCE_PERCENT / 100
    return (
        lower_shadow >= 2 * body * (1 - tolerance)
        and upper_shadow <= body * (1 + tolerance)
        and body / candle_range <= _SMALL_BODY_RATIO
    )


def _is_shooting_star(row):
    body = _body(row)
    candle_range = _candle_range(row)
    if candle_range == 0:
        return False

    upper_shadow = row["high_price"] - max(row["open_price"], row["close_price"])
    lower_shadow = min(row["open_price"], row["close_price"]) - row["low_price"]
    tolerance = SHADOW_TOLERANCE_PERCENT / 100
    return (
        upper_shadow >= 2 * body * (1 - tolerance)
        and lower_shadow <= body * (1 + tolerance)
        and body / candle_range <= _SMALL_BODY_RATIO
    )


def _result(name, direction, low_reference, high_reference):
    return {
        "candlestick_pattern": {
            "name": name,
            "low": min(low_reference["low_price"], high_reference["low_price"]),
            "high": max(low_reference["high_price"], high_reference["high_price"]),
        },
        "pattern_direction": direction,
    }
