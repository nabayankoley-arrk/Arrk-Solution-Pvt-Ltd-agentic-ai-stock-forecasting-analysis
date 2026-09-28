"""LLM Agent client for reconcile_and_decide.

Talks to whichever provider config.LLM_PROVIDER selects. OpenRouter
(https://openrouter.ai, hosted -- see config.py's OPENROUTER_* block) is
the hard default; a locally running Ollama server
(https://ollama.com, free/local) remains available as an opt-in fallback
for offline/local dev -- set LLM_PROVIDER=ollama in the environment to use
it.
Both are OpenAI-style chat completion APIs, but with different endpoint
shapes (Ollama's /api/chat vs. OpenRouter's OpenAI-compatible
/chat/completions) and auth (Ollama: none, local-only; OpenRouter: Bearer
API key), so each gets its own small request-building function below;
call_llm_chat() is the one provider-agnostic entry point everything else
in this package should use.

Neither provider's tool-calling support is depended on here -- it's
model-specific and inconsistent across the free/cheap models this is
meant to run against -- so instead of a `tools` parameter this prompts
the model to return one JSON object matching the specification's "LLM
Agent Decision Contract" directly, and parses that JSON out of the
response text. Simpler and more portable than depending on a given
model's function-calling support.

If the configured provider can't be reached (Ollama not running/model not
pulled, OpenRouter auth/network error) or returns something that doesn't
parse into a valid decision, get_decision() falls back to a deterministic
rule (see _fallback_decision) when config.LLM_FALLBACK_ENABLED is True, so
reconcile_and_decide -- and smoke_test.py -- keep working without a live
model. Set LLM_FALLBACK_ENABLED = False to make that a hard failure
instead.

call_llm_chat() and extract_json_object() are exported for reuse by other
LLM-driven capabilities in this package that aren't part of the
reconciliation decision contract -- e.g. forecast_price_range.py -- so
they share one provider-calling/JSON-parsing implementation rather than
each reimplementing it.
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import json
import re

import requests

from . import config

_SYSTEM_PROMPT = """You are the reconciliation agent of a stock-analysis orchestrator. For one \
ticker and one horizon you get compact results from the analysis pillars the horizon calls for, \
their weights, and a weighted baseline verdict computed from their directions. Decide whether \
to finalize now or rerun exactly one pillar first, and give the overall verdict.

Respond with ONLY one JSON object, no other text:
{
  "decision": "finalize" | "call_tool",
  "selected_tool": one of enabled_rerun_tools, or null,
  "tool_call_args": {},
  "overall_direction": "bullish" | "neutral" | "bearish",
  "confidence": "low" | "medium" | "high",
  "key_drivers": ["up to three short points: the signals that decide the verdict"],
  "conflicts": ["short points where the pillars disagree, or []"],
  "reason": "two or three sentences explaining the verdict for this horizon"
}

Rules:
- Judge for the horizon given in horizon_guidance, and weigh each pillar by pillar_weights. A \
pillar with status other than "ok" has no say.
- Start from baseline_verdict. Move away from it only for a reason visible in the results (for \
example a strong momentum signal with low volatility, or valuation risk flags), and say so.
- confidence is at most baseline_verdict's confidence; lower it when the results give a reason \
(for example weak or contradictory signals within a pillar).
- Choose "call_tool" only if rerunning one planned pillar could plausibly fill a genuine gap \
(for example it errored) and tool_loop_count is below max_tool_loops; otherwise finalize.
- Use only the figures given. Never invent prices, targets or data."""


class LLMAgentError(Exception):
    """Raised when the LLM Agent could not be reached or returned an
    unparsable/invalid decision, and no fallback is available."""


def get_decision(context):
    """context: the reconciliation payload built by reconcile_and_decide
    (ticker, horizon, horizon_guidance, pillar_weights, pillars (digests),
    pillar_status, baseline_verdict, tool_loop_count, max_tool_loops,
    enabled_rerun_tools).

    Returns {decision, selected_tool, tool_call_args, reason, verdict} with a
    verdict of {direction, confidence, key_drivers, conflicts}, falling back
    to the baseline verdict when the LLM cannot be reached.
    """
    try:
        return _parse_decision(_call_llm(context), context)
    except Exception as exc:
        if not config.LLM_FALLBACK_ENABLED:
            raise LLMAgentError(str(exc)) from exc
        return _fallback_decision(context, reason=f"LLM Agent unavailable ({exc}); used deterministic fallback")


def call_llm_chat(system_prompt, user_prompt, timeout=None):
    """Shared chat call -- any caller's system/user prompt pair, routed to
    whichever provider config.LLM_PROVIDER selects. Raises requests' usual
    exceptions on a network error or non-2xx response (or ValueError if
    LLM_PROVIDER is neither "ollama" nor "openrouter"); callers decide how
    to handle that (get_decision falls back to a deterministic rule, see
    module docstring).
    """
    if config.LLM_PROVIDER == "openrouter":
        model = config.OPENROUTER_MODEL
        raw = _call_openrouter_chat(system_prompt, user_prompt, timeout or config.OPENROUTER_TIMEOUT_SECONDS)
    elif config.LLM_PROVIDER == "ollama":
        model = config.OLLAMA_MODEL
        raw = _call_ollama_chat(system_prompt, user_prompt, timeout or config.OLLAMA_TIMEOUT_SECONDS)
    else:
        raise ValueError(f"unknown LLM_PROVIDER: {config.LLM_PROVIDER!r}")

    # Debug trace: confirms a real model reply arrived rather than
    # get_decision's deterministic fallback (which never reaches this
    # function -- it is only used when this call *raises*). An empty or
    # whitespace-only `raw` is the interesting case: the request succeeded,
    # so nothing raises, but _parse_decision then fails and the caller
    # silently falls back. Remove this print, or gate it behind a log
    # level, once the provider/model in use is known-good.
    print(
        f"[llm] provider={config.LLM_PROVIDER} model={model} "
        f"chars={len(raw or '')} raw={(raw or '')[:300]!r}",
        flush=True,
    )
    return raw


def _call_ollama_chat(system_prompt, user_prompt, timeout):
    response = requests.post(
        f"{config.OLLAMA_BASE_URL}/api/chat",
        json={
            "model": config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": config.LLM_TEMPERATURE},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def _call_openrouter_chat(system_prompt, user_prompt, timeout):
    """OpenRouter's /chat/completions is OpenAI-compatible, unlike Ollama's
    /api/chat -- different envelope (choices[0].message.content, not
    message.content directly) and Bearer-token auth instead of no auth at
    all. config.OPENROUTER_API_KEY is read from the environment only (see
    config.py) -- raises here rather than sending an unauthenticated
    request if it was never set.
    """
    if not config.OPENROUTER_API_KEY:
        raise LLMAgentError("OPENROUTER_API_KEY is not set (required when LLM_PROVIDER=openrouter)")

    response = requests.post(
        f"{config.OPENROUTER_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
        json={
            "model": config.OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.LLM_TEMPERATURE,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _call_llm(context):
    return call_llm_chat(_SYSTEM_PROMPT, _build_prompt(context))


def _build_prompt(context):
    return (
        f"ticker: {context['ticker']}\n"
        f"horizon: {context['horizon']}\n"
        f"horizon_guidance: {context['horizon_guidance']}\n"
        f"pillar_weights: {json.dumps(context['pillar_weights'])}\n"
        f"pillar_status: {json.dumps(context['pillar_status'])}\n"
        f"pillars: {json.dumps(context['pillars'], default=str)}\n"
        f"baseline_verdict: {json.dumps(context['baseline_verdict'])}\n"
        f"tool_loop_count: {context['tool_loop_count']}\n"
        f"max_tool_loops: {context['max_tool_loops']}\n"
        f"enabled_rerun_tools: {json.dumps(list(context['enabled_rerun_tools']))}\n"
    )


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json_object(raw_text):
    """Extracts and parses the first {...} object found in raw_text (the
    model is asked for "ONLY a single JSON object", but local models
    sometimes wrap it in prose anyway). Raises LLMAgentError if none is
    found or it doesn't parse as JSON -- callers decide how to handle
    that.
    """
    match = _JSON_OBJECT_RE.search(raw_text or "")
    if not match:
        raise LLMAgentError(f"no JSON object found in LLM response: {raw_text!r}")
    return json.loads(match.group(0))


_DIRECTIONS = ("bullish", "neutral", "bearish")
_CONFIDENCES = ("low", "medium", "high")


def _points(values, limit=3):
    return [str(v).strip()[:200] for v in (values or []) if str(v).strip()][:limit]


def _parse_decision(raw_text, context):
    decision = extract_json_object(raw_text)

    if decision.get("decision") not in ("finalize", "call_tool"):
        raise LLMAgentError(f"invalid decision value: {decision.get('decision')!r}")
    if decision["decision"] == "call_tool" and decision.get("selected_tool") not in context["enabled_rerun_tools"]:
        raise LLMAgentError(f"invalid selected_tool for call_tool: {decision.get('selected_tool')!r}")

    baseline = context["baseline_verdict"]
    direction = decision.get("overall_direction")
    if direction not in _DIRECTIONS:
        raise LLMAgentError(f"invalid overall_direction: {direction!r}")
    # The LLM may lean away from the weighted baseline, but not flip it outright.
    if {direction, baseline["direction"]} == {"bullish", "bearish"}:
        direction = baseline["direction"]
    # Confidence may be lowered from the baseline, never raised above it.
    confidence = baseline["confidence"]
    if decision.get("confidence") in _CONFIDENCES:
        confidence = _CONFIDENCES[min(_CONFIDENCES.index(decision["confidence"]), _CONFIDENCES.index(confidence))]

    return {
        "decision": decision["decision"],
        "selected_tool": decision.get("selected_tool") if decision["decision"] == "call_tool" else None,
        "tool_call_args": decision.get("tool_call_args") or {},
        "reason": str(decision.get("reason") or "").strip(),
        "verdict": {
            **baseline,
            "direction": direction if baseline["direction"] is not None else None,
            "confidence": confidence,
            "key_drivers": _points(decision.get("key_drivers")) or baseline["key_drivers"],
            "conflicts": _points(decision.get("conflicts")) or baseline["conflicts"],
        },
    }


def _fallback_decision(context, reason):
    """Deterministic stand-in when the LLM cannot be reached or returns
    garbage: finalize with the weighted baseline verdict. Never reruns a
    pillar -- there is no reasoning available to justify which one."""
    return {
        "decision": "finalize",
        "selected_tool": None,
        "tool_call_args": {},
        "reason": reason,
        "verdict": dict(context["baseline_verdict"]),
    }
