"""_verdict — the orchestrator's overall read of a ticker, and the pillar digests behind it.

weighted_verdict() is the deterministic verdict: each planned pillar's
direction scored bullish +1 / neutral 0 / bearish -1, weighted by the horizon's
plan (config.HORIZON_PLAN), over the pillars that actually produced a
direction. It is the fallback when the LLM cannot be reached, and the bounds
the LLM's own verdict is checked against (reconcile_and_decide.py).

Disagreement between pillars is reported in `conflicts` and lowers
`confidence`; it no longer pauses the run for a human review.

pillar_digests() gives the reconciliation and forecast prompts a compact view
of each pillar instead of its raw output.
"""

from .. import config

DIRECTION_SCORE = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}
PILLAR_FIELDS = {"technical": "technical_analysis", "fundamental": "fundamental_analysis", "sentiment": "sentiment_analysis"}
CONFIDENCE_ORDER = ("low", "medium", "high")


def pillar_direction(state, pillar):
    result = state.get(PILLAR_FIELDS[pillar]) or {}
    if pillar == "technical":
        return (result.get("technical_signal") or {}).get("direction")
    if pillar == "fundamental":
        return (result.get("composite") or {}).get("direction")
    return result.get("direction")


def weighted_verdict(state):
    weights = state.get("pillar_weights") or {}
    directions = {p: pillar_direction(state, p) for p in weights}
    available = {p: w for p, w in weights.items() if directions[p] in DIRECTION_SCORE}
    total = sum(weights.values()) or 1.0
    coverage = round(sum(available.values()) / total, 2)

    if not available:
        return {
            "direction": None, "confidence": "low", "score": None, "coverage": 0.0,
            "pillars": directions, "key_drivers": [], "conflicts": [],
        }

    score = sum(DIRECTION_SCORE[directions[p]] * w for p, w in available.items()) / sum(available.values())
    if score > config.VERDICT_NEUTRAL_BAND:
        direction = "bullish"
    elif score < -config.VERDICT_NEUTRAL_BAND:
        direction = "bearish"
    else:
        direction = "neutral"

    opposed = {"bullish": "bearish", "bearish": "bullish"}
    present = set(directions[p] for p in available)
    if direction in opposed:
        conflicts = [f"{p} is {directions[p]}" for p in available if directions[p] == opposed[direction]]
    else:
        conflicts = [f"{p} is {directions[p]}" for p in available if directions[p] != "neutral"] if {"bullish", "bearish"} <= present else []

    if coverage < 0.5 or {"bullish", "bearish"} <= present:
        confidence = "low"
    elif coverage >= 0.8 and not conflicts and abs(score) >= 0.5:
        confidence = "high"
    else:
        confidence = "medium"

    drivers = sorted(available, key=lambda p: -available[p])
    return {
        "direction": direction,
        "confidence": confidence,
        "score": round(score, 3),
        "coverage": coverage,
        "pillars": directions,
        "key_drivers": [f"{p} {directions[p]} (weight {weights[p]:.0%})" for p in drivers],
        "conflicts": conflicts,
    }


def cap_confidence(confidence, ceiling):
    """The lower of two confidence levels."""
    return CONFIDENCE_ORDER[min(CONFIDENCE_ORDER.index(confidence), CONFIDENCE_ORDER.index(ceiling))]


def pillar_digests(state):
    """{pillar: compact dict} for the planned pillars, None where a pillar has no result."""
    technical = state.get("technical_analysis") or {}
    fundamental = state.get("fundamental_analysis") or {}
    sentiment = state.get("sentiment_analysis") or {}
    signal = technical.get("technical_signal") or {}
    volatility = technical.get("volatility") or {}
    composite = fundamental.get("composite") or {}

    digests = {
        "technical": {
            "direction": signal.get("direction"),
            "confidence": technical.get("confidence"),
            "current_price": technical.get("current_price"),
            **{k: v for k, v in (signal.get("summary") or {}).items()},
            "atr_pct": (volatility.get("detail") or {}).get("atr_pct"),
            "candlestick_pattern": (technical.get("candlestick_pattern") or {}).get("pattern")
            if isinstance(technical.get("candlestick_pattern"), dict) else technical.get("candlestick_pattern"),
            "trade_setup": technical.get("trade_setup"),
        } if technical else None,
        "fundamental": {
            "direction": composite.get("direction"),
            "confidence": composite.get("confidence"),
            "risk_flags": composite.get("risk_flags"),
            "growth": (fundamental.get("growth") or {}).get("classification"),
            "financial_health": (fundamental.get("financial_health") or {}).get("classification"),
            "valuation": (fundamental.get("relative_valuation") or {}).get("classification"),
            "analyst_consensus": (fundamental.get("analyst_consensus") or {}).get("classification"),
            "data_tier": fundamental.get("data_tier"),
        } if fundamental else None,
        "sentiment": {
            "direction": sentiment.get("direction"),
            "coverage": sentiment.get("coverage"),
            "summary": sentiment.get("summary"),
            "sources": {
                source: {k: entry.get(k) for k in ("status", "document", "filed_on", "label", "management_tone", "guidance", "concerns")}
                for source, entry in (sentiment.get("sources") or {}).items()
            },
        } if sentiment else None,
    }
    return {p: digests[p] for p in (state.get("pillar_weights") or digests)}
