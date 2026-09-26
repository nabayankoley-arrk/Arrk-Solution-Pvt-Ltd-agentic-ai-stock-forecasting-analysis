"""build_final_response — terminal node.

The orchestrator's result: the planned pillars' outputs, the verdict
(direction, confidence, key drivers, conflicts -- nodes/_verdict.py) and the
LLM's explanation of it as `narrative`. With forecast_days, also a price range
(forecast_price_range.py, anchored on the technical pillar's volatility); a
forecasting failure never takes down the run.
"""

from ..forecast_price_range import forecast_price_range
from ._verdict import pillar_digests


def build_final_response(state):
    technical = state.get("technical_analysis") or {}
    fundamental = state.get("fundamental_analysis") or {}
    sentiment = state.get("sentiment_analysis") or {}
    errors = state.get("errors") or {}

    risk_flags = list((fundamental.get("composite") or {}).get("risk_flags") or [])
    risk_flags.extend(f"{pillar}: {reason}" for pillar, reason in errors.items() if reason)

    final_response = {
        "ticker": state.get("ticker"),
        "horizon": state.get("horizon"),
        "technical_summary": technical,
        "fundamental_summary": fundamental,
        "sentiment_summary": sentiment,
        "decision": state.get("decision"),
        "verdict": state.get("verdict"),
        "planned_pillars": state.get("planned_pillars"),
        "pillar_weights": state.get("pillar_weights"),
        "range_setup": technical.get("trade_setup"),
        "risk_flags": risk_flags,
        "narrative": state.get("reason"),
    }

    forecast_days = state.get("forecast_days")
    if forecast_days:
        try:
            final_response["price_forecast"] = forecast_price_range(final_response, forecast_days, pillar_digests(state))
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
