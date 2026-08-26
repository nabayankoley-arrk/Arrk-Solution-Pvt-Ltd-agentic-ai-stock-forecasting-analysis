"""aggregate_composite_signal — fan-in node.

Maps each of the four signals' classification to a -1..+1 score, applies
the weighted average from COMPOSITE_WEIGHTS with proportional
redistribution across whichever signals are available (any signal left as
classification=None, e.g. no analyst coverage, is simply excluded from both
the numerator and the denominator), and classifies the composite direction.
See docs/fundamental-analysis-design.md Section 3.2, row
`aggregate_composite_signal`, and Section 5 for the weight defaults.

TODO: confirm the score mapping and the neutral-band cutoff (currently
+/-0.15) against the full specification.
"""

from ..config import COMPOSITE_WEIGHTS

SCORE_MAP = {
    "relative_valuation": {"cheap": 1.0, "fair": 0.0, "expensive": -1.0},
    "growth": {"accelerating": 1.0, "stable": 0.0, "decelerating": -1.0},
    "financial_health": {"strong": 1.0, "stable": 0.0, "weak": -1.0},
    "analyst_consensus": {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0},
}

NEUTRAL_BAND = 0.15


def aggregate_composite_signal(state):
    available_weight = 0.0
    weighted_sum = 0.0
    risk_flags = []

    for signal_name, weight in COMPOSITE_WEIGHTS.items():
        signal = state.get(signal_name) or {}
        classification = signal.get("classification")
        if classification is None:
            continue

        score = SCORE_MAP[signal_name].get(classification)
        if score is None:
            continue

        weighted_sum += score * weight
        available_weight += weight
        risk_flags.extend(signal.get("detail", {}).get("risk_flags", []))

    if available_weight == 0:
        composite_direction = "neutral"
        composite_score = 0.0
    else:
        composite_score = weighted_sum / available_weight
        if composite_score > NEUTRAL_BAND:
            composite_direction = "bullish"
        elif composite_score < -NEUTRAL_BAND:
            composite_direction = "bearish"
        else:
            composite_direction = "neutral"

    composite_confidence = round(available_weight * 100, 2)

    return {
        "composite_result": {
            "direction": composite_direction,
            "score": composite_score,
            "confidence": composite_confidence,
            "risk_flags": risk_flags,
        }
    }
