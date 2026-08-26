"""aggregate_technical_signal — fan-in node.

Combines `trend` and `momentum` classifications into an overall direction
via a weighted vote (TREND_WEIGHT/MOMENTUM_WEIGHT), classified against
AGGREGATE_NEUTRAL_BAND. `support_resistance` doesn't carry a direction of
its own -- its levels are surfaced in the summary for downstream nodes/the
final response, not voted on. `volatility` doesn't vote either; instead it
discounts confidence via VOLATILITY_CONFIDENCE_MULTIPLIER, since a
"High" volatility read makes any directional signal less reliable, not
more or less bullish/bearish in itself.
"""

from ..config import AGGREGATE_NEUTRAL_BAND, MOMENTUM_WEIGHT, TREND_WEIGHT, VOLATILITY_CONFIDENCE_MULTIPLIER

_DIRECTION_SCORE = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}


def aggregate_technical_signal(state):
    trend = state.get("trend") or {}
    momentum = state.get("momentum") or {}
    volatility = state.get("volatility") or {}
    support_resistance = state.get("support_resistance") or {}

    trend_classification = trend.get("classification")
    momentum_classification = momentum.get("classification")
    volatility_classification = volatility.get("classification")

    trend_score = _DIRECTION_SCORE.get(trend_classification, 0.0)
    momentum_score = _DIRECTION_SCORE.get(momentum_classification, 0.0)

    combined_score = trend_score * TREND_WEIGHT + momentum_score * MOMENTUM_WEIGHT

    if combined_score > AGGREGATE_NEUTRAL_BAND:
        direction = "bullish"
    elif combined_score < -AGGREGATE_NEUTRAL_BAND:
        direction = "bearish"
    else:
        direction = "neutral"

    volatility_multiplier = VOLATILITY_CONFIDENCE_MULTIPLIER.get(volatility_classification, 1.0)
    confidence = round(min(abs(combined_score) * 100 * volatility_multiplier, 100.0), 2)

    technical_signal = {
        "direction": direction,
        "summary": {
            "trend": trend_classification,
            "momentum": momentum_classification,
            "volatility": volatility_classification,
            "support": support_resistance.get("support"),
            "resistance": support_resistance.get("resistance"),
        },
    }
    return {"technical_signal": technical_signal, "confidence": confidence}
