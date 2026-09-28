"""combine_sentiment_signals — fan-in node, deterministic.

A recency-weighted vote across whichever of transcript_score /
annual_report_score actually produced a direction, using
config.SOURCE_WEIGHTS and a half-life recency decay against each
document's age -- explicitly not an LLM step (specification: "Combine
Sentiment Signals is explicitly not an LLM step"). Mirrors
agents/fundamental_analysis/nodes/aggregate_composite_signal.py's
proportional-redistribution pattern: a source with no usable direction
(fetch failed, scoring failed, or RESCORE_ON_CACHE_MISS skipped it) is
excluded from both the numerator and the denominator rather than
penalising the vote -- the specification's "Computes over whichever
sources are actually available if one pillar's fetch failed."
"""

from ..config import NEUTRAL_BAND, RECENCY_HALF_LIFE_DAYS, SOURCE_WEIGHTS

DIRECTION_SCORE = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}

# source name -> (state key holding its score dict, state key holding its document)
SOURCES = {
    "transcript": ("transcript_score", "transcript_doc"),
    "annual_report": ("annual_report_score", "annual_report_doc"),
}


def _recency_weight(age_days):
    if age_days is None:
        return 1.0
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def combine_sentiment_signals(state):
    weighted_sum = 0.0
    available_weight = 0.0

    for source, (score_key, doc_key) in SOURCES.items():
        score = state.get(score_key)
        if not score or score.get("direction") is None:
            continue

        doc = state.get(doc_key) or {}
        weight = SOURCE_WEIGHTS.get(source, 0.0) * _recency_weight(doc.get("age_days"))
        weighted_sum += DIRECTION_SCORE[score["direction"]] * weight
        available_weight += weight

    if available_weight == 0:
        direction = None
        combined_score = None
    else:
        combined_score = weighted_sum / available_weight
        if combined_score > NEUTRAL_BAND:
            direction = "bullish"
        elif combined_score < -NEUTRAL_BAND:
            direction = "bearish"
        else:
            direction = "neutral"

    # How much of the full vote was actually available (0-100): one of two
    # sources, or a stale document, lowers it. Not a model confidence.
    max_weight = sum(SOURCE_WEIGHTS.values())
    coverage = round(available_weight / max_weight * 100, 2) if max_weight else 0.0

    return {
        "combined_sentiment": {
            "direction": direction,
            "score": None if combined_score is None else round(combined_score, 3),
            "coverage": coverage,
        }
    }
