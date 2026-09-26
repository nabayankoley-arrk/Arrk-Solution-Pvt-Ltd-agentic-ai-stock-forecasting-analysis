"""forecast_price_range — a price range for N days ahead, anchored on volatility.

Two steps, so a prediction is never just a number an LLM made up:

  1. A deterministic baseline from the technical pillar's ATR(14):
     half-width = FORECAST_ATR_MULTIPLIER * ATR * sqrt(days), centred on the
     current price and shifted by up to FORECAST_TILT of that half-width in the
     verdict's direction (less when the verdict's confidence is lower).
  2. The LLM reasons over the baseline, the verdict and the pillar digests and
     may move or narrow the range with a reason -- but the result is clamped to
     FORECAST_MAX_BAND_MULTIPLE half-widths either side of the current price,
     kept at least MIN_WIDTH_SHARE of the baseline's width, and its confidence
     can never exceed the verdict's.

If the LLM cannot be reached, the baseline itself is returned (method
"volatility_baseline"). Without an ATR there is no baseline: the LLM's range is
used with low confidence (method "llm_only"), or the forecast is unavailable.

This is a reasoned estimate from existing signals, not a trained or
statistically validated model; every result carries config.FORECAST_DISCLAIMER.
Called by build_final_response when the caller supplies forecast_days.
"""

import json
import math

from . import config
from .llm_client import LLMAgentError, call_llm_chat, extract_json_object

_DIRECTIONS = ("bullish", "neutral", "bearish")
_CONFIDENCES = ("low", "medium", "high")
_DIRECTION_SIGN = {"bullish": 1, "neutral": 0, "bearish": -1}
_CONFIDENCE_TILT = {"high": 1.0, "medium": 0.6, "low": 0.3}
MIN_WIDTH_SHARE = 0.5  # the LLM's range is at least this share of the baseline's width

_SYSTEM_PROMPT = """You estimate a plausible price range for one stock a given number of days \
ahead. You get the current price, a volatility baseline range computed from its ATR, the \
orchestrator's verdict for the horizon, and compact technical, fundamental and sentiment results.

Respond with ONLY one JSON object, no other text:
{
  "direction": "bullish" | "neutral" | "bearish",
  "expected_price_low": number,
  "expected_price_high": number,
  "confidence": "low" | "medium" | "high",
  "reasoning": "two or three sentences grounded in the given signals"
}

Rules:
- Start from baseline_range. Move or narrow it only for a reason in the inputs (support or \
resistance inside the range, a strong trend, valuation or analyst targets) and say which.
- The range must stay within allowed_range. expected_price_low <= expected_price_high.
- The further out forecast_days is, the wider the range: do not narrow a 60-day range to what \
would suit 5 days.
- confidence may not exceed the verdict's confidence; use "low" when pillars conflict.
- Use only the figures given. Never invent prices, targets or data."""


def _baseline(price, atr, days, verdict):
    half_width = config.FORECAST_ATR_MULTIPLIER * atr * math.sqrt(days)
    tilt = (
        config.FORECAST_TILT * half_width
        * _DIRECTION_SIGN.get(verdict.get("direction"), 0)
        * _CONFIDENCE_TILT.get(verdict.get("confidence"), 0.3)
    )
    low = max(price - half_width + tilt, 0.01)
    allowed = config.FORECAST_MAX_BAND_MULTIPLE * half_width
    return {
        "low": round(low, 2),
        "high": round(price + half_width + tilt, 2),
        "allowed_low": round(max(price - allowed, 0.01), 2),
        "allowed_high": round(price + allowed, 2),
    }


def _atr(technical):
    detail = (technical.get("volatility") or {}).get("detail") or {}
    atr = detail.get("atr")
    return atr if isinstance(atr, (int, float)) and atr > 0 else None


def forecast_price_range(final_response, forecast_days, pillar_digests=None):
    """final_response: build_final_response's output (ticker, technical_summary,
    verdict, ...). pillar_digests: _verdict.pillar_digests() for the prompt.

    Returns ticker, forecast_days, current_price, disclaimer, method, baseline,
    and either (unavailable=False) direction / expected_price_low /
    expected_price_high / confidence / reasoning, or (unavailable=True) reason.
    """
    if not isinstance(forecast_days, int) or isinstance(forecast_days, bool) or forecast_days <= 0:
        raise ValueError("forecast_days must be a positive integer")

    ticker = final_response.get("ticker")
    technical = final_response.get("technical_summary") or {}
    verdict = final_response.get("verdict") or {}
    price = technical.get("current_price")
    atr = _atr(technical)
    baseline = _baseline(price, atr, forecast_days, verdict) if price and atr else None
    verdict_confidence = verdict.get("confidence") if verdict.get("confidence") in _CONFIDENCES else "low"

    result = {
        "ticker": ticker,
        "forecast_days": forecast_days,
        "current_price": price,
        "baseline": baseline,
        "disclaimer": config.FORECAST_DISCLAIMER,
    }

    try:
        parsed = _parse_forecast(call_llm_chat(_SYSTEM_PROMPT, _build_prompt(
            ticker, price, forecast_days, baseline, verdict, pillar_digests, technical,
        )))
    except Exception as exc:
        if not config.LLM_FALLBACK_ENABLED:
            raise LLMAgentError(str(exc)) from exc
        if baseline is None:
            return {**result, "unavailable": True, "method": None,
                    "reason": f"no volatility data and the LLM Agent is unavailable ({exc})"}
        return {
            **result,
            "unavailable": False,
            "method": "volatility_baseline",
            "direction": verdict.get("direction") or "neutral",
            "expected_price_low": baseline["low"],
            "expected_price_high": baseline["high"],
            "confidence": "low",
            "reasoning": f"Range from recent volatility (ATR) over {forecast_days} days, shifted toward the "
                         f"{verdict.get('direction') or 'neutral'} verdict; no LLM reasoning was available.",
        }

    low, high = parsed["expected_price_low"], parsed["expected_price_high"]
    confidence = parsed["confidence"]
    method = "llm_only"
    if baseline:
        method = "volatility_anchored"
        # Not narrower than MIN_WIDTH_SHARE of the baseline: a long horizon
        # cannot be forecast as tightly as a few days.
        min_width = MIN_WIDTH_SHARE * (baseline["high"] - baseline["low"])
        if high - low < min_width:
            middle = (low + high) / 2
            low, high = middle - min_width / 2, middle + min_width / 2
            parsed["reasoning"] += " (Range widened to reflect the horizon's volatility.)"
        clamped_low = min(max(low, baseline["allowed_low"]), baseline["allowed_high"])
        clamped_high = min(max(high, baseline["allowed_low"]), baseline["allowed_high"])
        if (clamped_low, clamped_high) != (low, high):
            parsed["reasoning"] += " (Range limited to what recent volatility supports.)"
        low, high = clamped_low, clamped_high
        confidence = _CONFIDENCES[min(_CONFIDENCES.index(confidence), _CONFIDENCES.index(verdict_confidence))]
    else:
        confidence = "low"  # nothing to anchor it on

    return {
        **result,
        "unavailable": False,
        "method": method,
        "direction": parsed["direction"],
        "expected_price_low": round(low, 2),
        "expected_price_high": round(high, 2),
        "confidence": confidence,
        "reasoning": parsed["reasoning"],
    }


def _build_prompt(ticker, price, forecast_days, baseline, verdict, pillar_digests, technical):
    pillars = pillar_digests or {"technical": {
        "technical_signal": technical.get("technical_signal"),
        "support_resistance": technical.get("support_resistance"),
    }}
    return (
        f"ticker: {ticker}\n"
        f"current_price: {price}\n"
        f"forecast_days: {forecast_days}\n"
        f"baseline_range: {json.dumps({k: baseline[k] for k in ('low', 'high')}) if baseline else 'not available (no ATR)'}\n"
        f"allowed_range: {json.dumps({'low': baseline['allowed_low'], 'high': baseline['allowed_high']}) if baseline else 'not available'}\n"
        f"verdict: {json.dumps({k: verdict.get(k) for k in ('direction', 'confidence', 'key_drivers', 'conflicts')})}\n"
        f"support_resistance: {json.dumps(technical.get('support_resistance'))}\n"
        f"pillars: {json.dumps(pillars, default=str)}\n"
    )


def _parse_forecast(raw_text):
    parsed = extract_json_object(raw_text)

    if parsed.get("direction") not in _DIRECTIONS:
        raise LLMAgentError(f"invalid direction: {parsed.get('direction')!r}")
    low, high = parsed.get("expected_price_low"), parsed.get("expected_price_high")
    for label, value in (("expected_price_low", low), ("expected_price_high", high)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise LLMAgentError(f"invalid {label}: {value!r}")
    if low > high:
        raise LLMAgentError(f"expected_price_low ({low}) is greater than expected_price_high ({high})")
    if parsed.get("confidence") not in _CONFIDENCES:
        raise LLMAgentError(f"invalid confidence: {parsed.get('confidence')!r}")

    return {
        "direction": parsed["direction"],
        "expected_price_low": float(low),
        "expected_price_high": float(high),
        "confidence": parsed["confidence"],
        "reasoning": str(parsed.get("reasoning") or ""),
    }
