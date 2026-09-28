"""forecast_price_range — a price range for N days ahead, anchored on volatility.

Two steps, so a prediction is never just a number an LLM made up:

  1. A deterministic baseline, log-normal around a centre:
         low / high = centre * exp(-/+ FORECAST_SIGMA_MULTIPLIER * sigma * sqrt(trading days))
     sigma is the technical pillar's daily return volatility
     (daily_return_std_pct; ATR / 1.4 when missing), and trading days are
     calendar days * 252/365. With the default multiplier this is roughly a 68%
     range, and it can never reach zero. The centre is the current price,
     shifted by up to FORECAST_TILT of the half-width in the verdict's direction
     (less at lower confidence) -- except for short-term forecasts, which stay
     centred on the current price (config.FORECAST_TILT_SHORT_TERM: the
     technical signal behind them showed no directional edge in backtests). From FORECAST_ANALYST_FROM_DAYS on, when enough
     analysts cover the stock, the centre also moves toward their average
     12-month target -- up to FORECAST_ANALYST_MAX_PULL of the way at a year --
     which is how fundamentals reach a long-term price.
  2. The LLM reasons over the baseline, the verdict and the pillar digests and
     may move or narrow the range with a reason -- but the result is clamped to
     FORECAST_MAX_BAND_MULTIPLE half-widths around the centre, kept at least
     MIN_WIDTH_SHARE of the baseline's width, and its confidence can never
     exceed the verdict's.

If the LLM cannot be reached, the baseline itself is returned (method
"volatility_baseline"). Without volatility data there is no baseline: the LLM's
range is used with low confidence (method "llm_only"), or the forecast is
unavailable. Beyond FORECAST_MAX_DAYS no range is given at all.

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
_ATR_TO_SIGMA = 1.4  # ATR (high-low range) runs ~1.3-1.5x the daily close-to-close move
MIN_WIDTH_SHARE = 0.5  # the LLM's range is at least this share of the baseline's width

_SYSTEM_PROMPT = """You estimate a plausible price range for one stock a given number of days \
ahead. You get the current price, a baseline range computed from its daily volatility (shifted \
toward the verdict and, for long horizons, toward the analysts' average target), the \
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
- If forecast_days is 14 or less, keep the range centred on the current price: do not shift it \
up or down because of the direction of the technical signal, which has shown no directional \
edge in backtests. You may still narrow a side for a nearby support or resistance level.
- The range must stay within allowed_range. expected_price_low <= expected_price_high.
- The further out forecast_days is, the wider the range: do not narrow a 60-day range to what \
would suit 5 days.
- confidence may not exceed the verdict's confidence; lower it when the signals inside the \
range point different ways.
- Use only the figures given. Never invent prices, targets or data."""


def _daily_sigma(technical):
    """Daily return volatility as a fraction, or None."""
    detail = (technical.get("volatility") or {}).get("detail") or {}
    std_pct = detail.get("daily_return_std_pct")
    if isinstance(std_pct, (int, float)) and std_pct > 0:
        return std_pct / 100
    atr_pct = detail.get("atr_pct")
    if isinstance(atr_pct, (int, float)) and atr_pct > 0:
        return atr_pct / 100 / _ATR_TO_SIGMA
    return None


def _analyst_target(fundamental):
    """(average target, analyst count) when coverage is broad enough, else (None, None)."""
    detail = (fundamental.get("analyst_consensus") or {}).get("detail") or {}
    target, count = detail.get("avg_price_target"), detail.get("num_analysts") or 0
    if isinstance(target, (int, float)) and target > 0 and count >= config.FORECAST_ANALYST_MIN_COUNT:
        return target, count
    return None, None


def _baseline(price, sigma, days, verdict, target=None):
    trading_days = days * config.TRADING_DAYS_PER_YEAR / 365
    half = config.FORECAST_SIGMA_MULTIPLIER * sigma * math.sqrt(trading_days)  # in log space
    short_term = days <= config.SHORT_TERM_MAX_DAYS
    tilt = 0.0 if short_term and not config.FORECAST_TILT_SHORT_TERM else (
        config.FORECAST_TILT * half
        * _DIRECTION_SIGN.get(verdict.get("direction"), 0)
        * _CONFIDENCE_TILT.get(verdict.get("confidence"), 0.3)
    )
    centre = math.log(price) + tilt
    pull = 0.0
    if target and days >= config.FORECAST_ANALYST_FROM_DAYS:
        pull = config.FORECAST_ANALYST_MAX_PULL * min(days / 365, 1.0)
        centre = (1 - pull) * centre + pull * math.log(target)
    allowed = config.FORECAST_MAX_BAND_MULTIPLE * half
    return {
        "low": round(math.exp(centre - half), 2),
        "high": round(math.exp(centre + half), 2),
        "allowed_low": round(math.exp(centre - allowed), 2),
        "allowed_high": round(math.exp(centre + allowed), 2),
        "daily_volatility_pct": round(sigma * 100, 2),
        "analyst_pull": round(pull, 2),
    }


def forecast_price_range(final_response, forecast_days, pillar_digests=None):
    """final_response: build_final_response's output (ticker, technical_summary,
    fundamental_summary, verdict, ...). pillar_digests: _verdict.pillar_digests().

    Returns ticker, forecast_days, current_price, disclaimer, method, baseline,
    analyst_target, and either (unavailable=False) direction /
    expected_price_low / expected_price_high / confidence / reasoning, or
    (unavailable=True) reason.
    """
    if not isinstance(forecast_days, int) or isinstance(forecast_days, bool) or forecast_days <= 0:
        raise ValueError("forecast_days must be a positive integer")

    ticker = final_response.get("ticker")
    technical = final_response.get("technical_summary") or {}
    fundamental = final_response.get("fundamental_summary") or {}
    verdict = final_response.get("verdict") or {}
    raw_price = technical.get("current_price")
    price = round(raw_price, 2) if isinstance(raw_price, (int, float)) else None
    result = {
        "ticker": ticker,
        "forecast_days": forecast_days,
        "current_price": price,
        "disclaimer": config.FORECAST_DISCLAIMER,
    }

    if forecast_days > config.FORECAST_MAX_DAYS:
        return {**result, "unavailable": True, "method": None, "baseline": None,
                "reason": f"a price range more than {config.FORECAST_MAX_DAYS // 365} years ahead is not meaningful "
                          "from these signals; the verdict and its drivers still apply"}

    sigma = _daily_sigma(technical)
    target, analysts = _analyst_target(fundamental)
    baseline = _baseline(price, sigma, forecast_days, verdict, target) if price and sigma else None
    verdict_confidence = verdict.get("confidence") if verdict.get("confidence") in _CONFIDENCES else "low"
    result.update(
        baseline=baseline,
        analyst_target={"avg_price_target": target, "num_analysts": analysts} if target else None,
    )

    try:
        parsed = _parse_forecast(call_llm_chat(_SYSTEM_PROMPT, _build_prompt(
            ticker, price, forecast_days, baseline, verdict, pillar_digests, technical, result["analyst_target"],
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
            "reasoning": f"Range from recent daily volatility over {forecast_days} days, shifted toward the "
                         f"{verdict.get('direction') or 'neutral'} verdict"
                         + (" and the analysts' average target" if baseline["analyst_pull"] else "")
                         + "; no LLM reasoning was available.",
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


def _build_prompt(ticker, price, forecast_days, baseline, verdict, pillar_digests, technical, analyst_target):
    pillars = pillar_digests or {"technical": {
        "technical_signal": technical.get("technical_signal"),
        "support_resistance": technical.get("support_resistance"),
    }}
    return (
        f"ticker: {ticker}\n"
        f"current_price: {price}\n"
        f"forecast_days: {forecast_days}\n"
        f"baseline_range: {json.dumps({k: baseline[k] for k in ('low', 'high')}) if baseline else 'not available (no volatility data)'}\n"
        f"allowed_range: {json.dumps({'low': baseline['allowed_low'], 'high': baseline['allowed_high']}) if baseline else 'not available'}\n"
        f"daily_volatility_pct: {baseline['daily_volatility_pct'] if baseline else 'not available'}\n"
        f"analyst_target: {json.dumps(analyst_target) if analyst_target else 'not available'}"
        f"{' (baseline centre moved ' + str(int(baseline['analyst_pull'] * 100)) + '% toward it)' if baseline and baseline['analyst_pull'] else ''}\n"
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
