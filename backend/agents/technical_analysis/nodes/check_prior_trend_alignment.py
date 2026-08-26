"""check_prior_trend_alignment — guard node.

Only reached when detect_candlestick_pattern found a pattern (see
graph.py's routing). Verifies a bullish reversal pattern followed a
bearish trend, and a bearish reversal pattern followed a bullish trend;
anything else (including a neutral prevailing trend) fails alignment.
"""


def check_prior_trend_alignment(state):
    trend = state.get("trend") or {}
    trend_classification = trend.get("classification")
    pattern_direction = state.get("pattern_direction")

    required_prior_trend = "bearish" if pattern_direction == "bullish" else "bullish"
    if trend_classification == required_prior_trend:
        return {"prior_trend_ok": {"passed": True, "reason": None}}

    reason = (
        f"{pattern_direction} reversal pattern requires a prior "
        f"{'downtrend' if pattern_direction == 'bullish' else 'uptrend'}, "
        f"but the prevailing trend is {trend_classification or 'unknown'}"
    )
    return {"prior_trend_ok": {"passed": False, "reason": reason}}
