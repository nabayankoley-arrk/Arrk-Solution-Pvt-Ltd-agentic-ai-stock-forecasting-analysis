"""forecast_price_range — LLM-reasoned price range estimate.

NOT part of the Orchestrator Subgraph specification. This is a new
capability, added per explicit direction: "by considering all this steps
i will need to forecast price of any stock for 30 day 60 day". Of the two
approaches discussed, this is the one chosen -- an LLM reasoning over the
orchestrator's existing pillar outputs, not a trained/statistical
time-series model. No new ingestion, no training pipeline, no new
dependency: it reuses the same Technical/Fundamental/Sentiment results
reconcile_and_decide already computes, and the same LLM Agent backend
(see llm_client.call_llm_chat -- whichever of Ollama/OpenRouter
config.LLM_PROVIDER selects), just with a different system prompt and a
different output shape.

This produces a qualitative estimate grounded in already-computed
signals, NOT a statistically validated forecast -- every result carries
config.FORECAST_DISCLAIMER so nothing downstream can present it as more
rigorous than it is. Unlike reconcile_and_decide, there is no
deterministic fallback when the LLM can't be reached: a rule-based
reconciliation fallback is possible because "finalize vs. call_tool" has
a sensible non-LLM default, but there is no non-LLM way to produce a
reasoned price range at all -- see forecast_price_range()'s failure path
below, which returns unavailable=True rather than inventing a number.

Wired into orchestrator/graph.py indirectly, through build_final_response:
when a caller supplies forecast_days as part of the graph's input (see
state.py's note on that field), build_final_response calls this
automatically and attaches the result to final_response["price_forecast"].
forecast_days stays outside the orchestrator's core input/state contract
otherwise -- it's still not part of the lead's specification, just an
optional extra. Callers that don't need forecasting simply omit it and pay
no extra LLM call:

    result = graph.invoke({"ticker": "WIPRO.NS", "horizon": "medium_term", "forecast_days": 30}, config=thread_config)
    # ... resume past any human-review pause first, see smoke_test.py ...
    result["final_response"]["price_forecast"]

This function also stays directly callable for cases build_final_response
doesn't cover -- e.g. asking for several forecast_days values (30 and 60)
against one already-completed run without rerunning the whole graph, see
forecast_smoke_test.py:

    forecast = forecast_price_range(result["final_response"], forecast_days=60)
"""

import json

from . import config
from .llm_client import LLMAgentError, call_llm_chat, extract_json_object

_SYSTEM_PROMPT = """You are a stock price-range estimator. You are given a ticker's current price and \
the latest Technical, Fundamental, and Sentiment analysis for it, and must reason out a PLAUSIBLE price \
range for a specific number of days from now.

This is a qualitative, reasoning-based estimate -- not a statistical or trained forecasting model. Ground \
your range in the signals you are given (trend, momentum, support/resistance, valuation, growth, analyst \
targets); do not invent information not present in the inputs.

Respond with ONLY a single JSON object, no other text, matching this shape:
{
  "direction": "bullish" | "bearish" | "neutral",
  "expected_price_low": number,
  "expected_price_high": number,
  "confidence": "low" | "medium" | "high",
  "reasoning": "concise explanation grounded in the given signals"
}

Rules:
- expected_price_low must be <= expected_price_high. Both bounds may sit above or below current_price for
  a strongly directional call -- the range does not need to straddle the current price.
- The further out forecast_days is, the wider the plausible range should be -- do not give a narrow range
  for a 60-day horizon that would only make sense for a 5-day one.
- confidence should be "low" whenever pillars disagree, a pillar is unavailable, or the horizon is long."""


def forecast_price_range(final_response, forecast_days):
    """final_response: an orchestrator run's build_final_response output
    (has ticker, technical_summary, fundamental_summary,
    sentiment_summary -- e.g. graph.invoke(...)["final_response"]).
    forecast_days: positive integer, how many days out to estimate for.

    Returns a dict with ticker, forecast_days, current_price, disclaimer,
    and either (unavailable=False) direction/expected_price_low/
    expected_price_high/confidence/reasoning, or (unavailable=True) reason.
    """
    if not isinstance(forecast_days, int) or isinstance(forecast_days, bool) or forecast_days <= 0:
        raise ValueError("forecast_days must be a positive integer")

    ticker = final_response.get("ticker")
    technical = final_response.get("technical_summary") or {}
    fundamental = final_response.get("fundamental_summary") or {}
    sentiment = final_response.get("sentiment_summary") or {}
    current_price = technical.get("current_price")

    prompt = _build_prompt(ticker, current_price, forecast_days, technical, fundamental, sentiment)

    try:
        raw_text = call_llm_chat(_SYSTEM_PROMPT, prompt)
        parsed = _parse_forecast(raw_text)
    except Exception as exc:
        if not config.LLM_FALLBACK_ENABLED:
            raise LLMAgentError(str(exc)) from exc
        return {
            "ticker": ticker,
            "forecast_days": forecast_days,
            "current_price": current_price,
            "unavailable": True,
            "reason": (
                f"LLM Agent unavailable ({exc}); no statistical fallback exists for this estimate -- "
                "see forecast_price_range.py's module docstring"
            ),
            "disclaimer": config.FORECAST_DISCLAIMER,
        }

    return {
        "ticker": ticker,
        "forecast_days": forecast_days,
        "current_price": current_price,
        "unavailable": False,
        "direction": parsed["direction"],
        "expected_price_low": parsed["expected_price_low"],
        "expected_price_high": parsed["expected_price_high"],
        "confidence": parsed["confidence"],
        "reasoning": parsed["reasoning"],
        "disclaimer": config.FORECAST_DISCLAIMER,
    }


def _build_prompt(ticker, current_price, forecast_days, technical, fundamental, sentiment):
    return (
        f"ticker: {ticker}\n"
        f"current_price: {current_price}\n"
        f"forecast_days: {forecast_days}\n"
        f"technical_signal: {json.dumps(technical.get('technical_signal'))}\n"
        f"support_resistance: {json.dumps(technical.get('support_resistance'))}\n"
        f"candlestick_pattern: {json.dumps(technical.get('candlestick_pattern'))}\n"
        f"trade_setup: {json.dumps(technical.get('trade_setup'))}\n"
        f"fundamental_composite: {json.dumps(fundamental.get('composite'))}\n"
        f"relative_valuation: {json.dumps(fundamental.get('relative_valuation'))}\n"
        f"growth: {json.dumps(fundamental.get('growth'))}\n"
        f"financial_health: {json.dumps(fundamental.get('financial_health'))}\n"
        f"analyst_consensus: {json.dumps(fundamental.get('analyst_consensus'))}\n"
        f"sentiment: {json.dumps(sentiment) if sentiment.get('direction') is not None else 'not available'}\n"
    )


def _parse_forecast(raw_text):
    parsed = extract_json_object(raw_text)

    if parsed.get("direction") not in ("bullish", "bearish", "neutral"):
        raise LLMAgentError(f"invalid direction: {parsed.get('direction')!r}")

    low, high = parsed.get("expected_price_low"), parsed.get("expected_price_high")
    if not isinstance(low, (int, float)) or isinstance(low, bool):
        raise LLMAgentError(f"invalid expected_price_low: {low!r}")
    if not isinstance(high, (int, float)) or isinstance(high, bool):
        raise LLMAgentError(f"invalid expected_price_high: {high!r}")
    if low > high:
        raise LLMAgentError(f"expected_price_low ({low}) is greater than expected_price_high ({high})")

    if parsed.get("confidence") not in ("low", "medium", "high"):
        raise LLMAgentError(f"invalid confidence: {parsed.get('confidence')!r}")

    return {
        "direction": parsed["direction"],
        "expected_price_low": low,
        "expected_price_high": high,
        "confidence": parsed["confidence"],
        "reasoning": parsed.get("reasoning") or "",
    }
