"""build_final_response — terminal node.

Consolidates the available pillar results, decision context, and review
status into the payload the specification's "Final Response" section
describes. Reached either directly (requires_review = False) or after
request_human_review's reviewer approves/edits (see graph.py).

When the caller supplied forecast_days (see state.py's note on that
field), also attaches a "price_forecast" key by calling
forecast_price_range.py over the same summaries just assembled below --
one extra LLM call, made only when asked for. forecast_price_range()
already returns an unavailable=True payload instead of raising when its
own LLM call fails and config.LLM_FALLBACK_ENABLED is True (the default);
the try/except here only guards the remaining case
(LLM_FALLBACK_ENABLED = False, or any other unexpected error) so a
forecasting failure never takes down the whole orchestrator run.
"""

from ..forecast_price_range import forecast_price_range


def build_final_response(state):
    technical = state.get("technical_analysis") or {}
    fundamental = state.get("fundamental_analysis") or {}
    sentiment = state.get("sentiment_analysis") or {}
    errors = state.get("errors") or {}

    reviewer_decision = state.get("reviewer_decision")
    review_status = "shipped_after_human_review" if reviewer_decision in ("approve", "edit") else "shipped_directly"
    narrative = state.get("review_notes") if reviewer_decision == "edit" else state.get("reason")

    risk_flags = list((fundamental.get("composite") or {}).get("risk_flags") or [])
    risk_flags.extend(f"{pillar}: {reason}" for pillar, reason in errors.items() if reason)

    final_response = {
        "ticker": state.get("ticker"),
        "horizon": state.get("horizon"),
        "technical_summary": technical,
        "fundamental_summary": fundamental,
        "sentiment_summary": sentiment,
        "decision": state.get("decision"),
        "range_setup": technical.get("trade_setup"),
        "risk_flags": risk_flags,
        "narrative": narrative,
        "review_status": review_status,
        "reviewer_decision": reviewer_decision,
    }

    forecast_days = state.get("forecast_days")
    if forecast_days:
        try:
            final_response["price_forecast"] = forecast_price_range(final_response, forecast_days)
        except Exception as exc:
            final_response["price_forecast"] = {
                "ticker": state.get("ticker"),
                "forecast_days": forecast_days,
                "unavailable": True,
                "reason": f"price forecast failed: {exc}",
            }
    else:
        final_response["price_forecast"] = None

    return {"final_response": final_response}
