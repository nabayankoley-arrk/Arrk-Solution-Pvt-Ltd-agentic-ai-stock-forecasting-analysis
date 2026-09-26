"""Reads Orchestrator results, so main.py and the agent never need to know
the shape of the Orchestrator's output.

outcome()               -- how a direct (explicit-ticker) analysis ended
analysis_digest()       -- the user-facing facts of a final_response: analyze_stock's tool result
format_analysis_reply() -- the same facts as a fixed-template sentence (fallback)
"""


def outcome(result):
    """How an Orchestrator run in the graph's state ended:

    analysis -- it produced a final_response
    invalid  -- it rejected the input (its error_response)
    failed   -- it raised; _orchestrator.run_orchestrator caught it
    """
    orchestrator_result = result.get("orchestrator_result")
    if orchestrator_result is None:
        return "failed"
    return "analysis" if orchestrator_result.get("final_response") else "invalid"


# Phrases that mark a string as an internal/operational detail rather than
# something a caller asked about: an unbuilt subgraph, an unreachable LLM
# provider, a database problem, a raw exception or a leaked URL. The
# Orchestrator puts these in `risk_flags` and in the decision `reason` (which
# becomes `narrative`) on purpose -- they belong in orchestrator_runs and in
# the logs, where they are needed for debugging. They just should not be read
# back to someone who asked how a stock looks: "Sentiment Analysis subgraph is
# not yet implemented" and "LLM Agent unavailable (429 Client Error ... )" are
# statements about this deployment, not about the ticker.
#
# Matched case-insensitively as substrings, so the surrounding wording (the
# "sentiment: " prefix the Orchestrator adds, the exception text appended after
# a marker) does not have to be predicted exactly.
_INTERNAL_DETAIL_MARKERS = (
    "not yet implemented",
    "not implemented",
    "llm agent unavailable",
    "deterministic fallback",
    "database connection failed",
    "connection failed",
    "client error",
    "server error",
    "traceback",
    "://",
)


def is_internal_detail(text):
    if not text:
        return False
    lowered = str(text).lower()
    return any(marker in lowered for marker in _INTERNAL_DETAIL_MARKERS)


def _is_unavailable_summary(label, summary):
    """A pillar can come back without an "error" key and still be empty --
    the Sentiment Agent returns a well-formed dict of Nones (see
    agents/orchestrator/nodes/fetch_sentiment_analysis.py). Treat a summary
    whose own directional verdict is missing as unavailable."""
    if label == "technical":
        return not (summary.get("technical_signal") or {}).get("direction")
    if label == "fundamental":
        return not (summary.get("composite") or {}).get("direction")
    return not summary.get("direction")


def _user_facing_flags(risk_flags):
    """Drops operational noise, keeping genuine analytical risk flags (e.g.
    the Fundamental Agent's own composite risk_flags, or a real pillar
    disagreement) -- those are about the ticker and belong in the reply."""
    return [flag for flag in risk_flags if not is_internal_detail(flag)]


def _facts(response):
    """The user-facing facts of a final_response (see
    agents/orchestrator/nodes/build_final_response.py), internal detail removed."""
    technical = response.get("technical_summary") or {}
    fundamental = response.get("fundamental_summary") or {}
    sentiment = response.get("sentiment_summary") or {}
    fundamental_composite = fundamental.get("composite") or {}
    verdict = response.get("verdict") or {}
    planned = response.get("planned_pillars") or ["technical", "fundamental", "sentiment"]
    support_resistance = technical.get("support_resistance") or {}
    narrative = response.get("narrative")

    # Filtering the internal flags would otherwise let a partial read look
    # like a complete one. Name the missing pillars plainly instead -- which
    # pillar had nothing to say is the caller's business; why is not. A
    # pillar the horizon did not call for is "not_used", not missing.
    unavailable = [
        label
        for label, summary in (("technical", technical), ("fundamental", fundamental), ("sentiment", sentiment))
        if label in planned and (not summary or "error" in summary or _is_unavailable_summary(label, summary))
    ]
    return {
        "ticker": response.get("ticker"),
        "horizon": response.get("horizon"),
        "current_price": technical.get("current_price"),
        "direction": verdict.get("direction"),
        "confidence": verdict.get("confidence"),
        "key_drivers": verdict.get("key_drivers") or [],
        "conflicts": verdict.get("conflicts") or [],
        "pillar_weights": response.get("pillar_weights"),
        "not_used": [p for p in ("technical", "fundamental", "sentiment") if p not in planned],
        "support": support_resistance.get("support"),
        "resistance": support_resistance.get("resistance"),
        "risk_flags": _user_facing_flags(response.get("risk_flags") or []),
        "narrative": None if is_internal_detail(narrative) else narrative,
        "unavailable_pillars": unavailable,
        "_technical": technical,
        "_fundamental": fundamental_composite,
        "_sentiment": sentiment,
    }


def _compact(value, max_chars=600):
    """Drops empty values and internal detail, and truncates long text, so a
    pillar summary fits in a prompt."""
    if isinstance(value, dict):
        kept = {k: _compact(v, max_chars) for k, v in value.items() if k != "error" and v not in (None, "", [], {})}
        return {k: v for k, v in kept.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_compact(v, max_chars) for v in value[:10] if not is_internal_detail(v)]
    if isinstance(value, str):
        return None if is_internal_detail(value) else value[:max_chars]
    return value


def analysis_digest(response):
    """A compact, user-facing view of a final_response: analyze_stock's tool result."""
    facts = _facts(response)
    digest = {k: v for k, v in facts.items() if not k.startswith("_")}
    digest["technical"] = _compact(
        {
            key: facts["_technical"].get(key)
            for key in ("as_of_date", "technical_signal", "volatility", "candlestick_pattern", "pattern_direction", "trade_setup")
        }
    )
    if "fundamental" not in facts["not_used"]:
        digest["fundamental"] = _compact(facts["_fundamental"])
    if "sentiment" not in facts["unavailable_pillars"] + facts["not_used"]:
        digest["sentiment"] = _compact(
            {key: facts["_sentiment"].get(key) for key in ("direction", "coverage", "summary", "sources")}
        )
    forecast = response.get("price_forecast")
    if forecast and not forecast.get("unavailable"):
        digest["price_forecast"] = _compact(forecast)
    return _compact(digest)


def format_analysis_reply(response):
    """The fixed-template chat reply, used when the agent's LLM call fails."""
    facts = _facts(response)
    ticker = facts["ticker"]

    parts = [f"Here's what I found for {ticker}:" if ticker else "Here's what I found:"]
    if facts["current_price"] is not None:
        parts.append(f"Current price: {facts['current_price']}.")
    if facts["direction"]:
        horizon = (facts["horizon"] or "").replace("_", " ")
        parts.append(f"Overall {horizon} view: {facts['direction']}" + (f", {facts['confidence']} confidence." if facts["confidence"] else "."))
    if facts["conflicts"]:
        parts.append(f"Conflicting signals: {'; '.join(facts['conflicts'][:2])}.")
    if facts["support"] is not None and facts["resistance"] is not None:
        parts.append(f"Support around {facts['support']}, resistance around {facts['resistance']}.")
    if facts["risk_flags"]:
        parts.append(f"Flags to note: {', '.join(str(flag) for flag in facts['risk_flags'][:3])}.")

    missing = facts["unavailable_pillars"]
    if missing:
        listed = " and ".join(missing) if len(missing) < 3 else ", ".join(missing[:-1]) + " and " + missing[-1]
        parts.append(f"This read is based on partial data -- {listed} analysis wasn't available.")

    forecast = response.get("price_forecast") or {}
    if forecast and not forecast.get("unavailable"):
        parts.append(
            f"Estimated range in {forecast['forecast_days']} days: {forecast['expected_price_low']}"
            f"-{forecast['expected_price_high']} ({forecast['confidence']} confidence; an estimate, not a guarantee)."
        )
    if facts["narrative"]:
        parts.append(f"Note: {facts['narrative']}")
    if len(parts) == 1:
        parts.append("The underlying data didn't have a clear signal to summarize.")
    return " ".join(parts)
