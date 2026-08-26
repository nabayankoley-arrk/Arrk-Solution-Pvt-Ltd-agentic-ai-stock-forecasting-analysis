"""compute_support_resistance — signal node (runs in parallel with the
other compute_* nodes after fetch_price_history).

Finds swing highs/lows within the trailing SUPPLY_DEMAND_WINDOW days (a
candle is a swing point if its high/low is the most extreme among itself
and SWING_ARM_LENGTH candles on each side), then picks the nearest swing
high above the current price as resistance and the nearest swing low
below it as support. Falls back to the window's own high/low when no
swing point qualifies on the required side (e.g. price is at a new high
for the window).
"""

from ..config import SUPPLY_DEMAND_WINDOW, SWING_ARM_LENGTH


def compute_support_resistance(state):
    history = state.get("price_history") or []
    window = history[-SUPPLY_DEMAND_WINDOW:]
    current_price = window[-1]["close_price"] if window else None

    if current_price is None:
        return {
            "support_resistance": {
                "support": None,
                "resistance": None,
                "detail": {"reason": "no price history"},
            }
        }

    arm = SWING_ARM_LENGTH
    n = len(window)
    swing_highs, swing_lows = [], []
    for i in range(arm, n - arm):
        high_slice = [window[j]["high_price"] for j in range(i - arm, i + arm + 1)]
        if window[i]["high_price"] == max(high_slice):
            swing_highs.append(window[i]["high_price"])

        low_slice = [window[j]["low_price"] for j in range(i - arm, i + arm + 1)]
        if window[i]["low_price"] == min(low_slice):
            swing_lows.append(window[i]["low_price"])

    resistance_candidates = [h for h in swing_highs if h > current_price]
    resistance = min(resistance_candidates) if resistance_candidates else None

    support_candidates = [l for l in swing_lows if l < current_price]
    support = max(support_candidates) if support_candidates else None

    if resistance is None:
        window_high = max(row["high_price"] for row in window)
        resistance = window_high if window_high > current_price else None

    if support is None:
        window_low = min(row["low_price"] for row in window)
        support = window_low if window_low < current_price else None

    detail = {
        "window_days": n,
        "swing_high_count": len(swing_highs),
        "swing_low_count": len(swing_lows),
    }
    return {
        "support_resistance": {
            "support": _round(support),
            "resistance": _round(resistance),
            "detail": detail,
        }
    }


def _round(value):
    return round(value, 4) if value is not None else None
