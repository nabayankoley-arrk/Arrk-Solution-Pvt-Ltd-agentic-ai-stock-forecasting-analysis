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

import json
import re

import requests

from . import config

_SYSTEM_PROMPT = """You are the reconciliation agent for a stock-analysis orchestrator. \
You are given the latest Technical, Fundamental, and Sentiment analysis results for one \
ticker and must decide whether the orchestrator can finalize its response now, or should \
rerun exactly one analysis pillar to get more information first.

Respond with ONLY a single JSON object, no other text, matching this shape:
{
  "decision": "finalize" | "call_tool",
  "selected_tool": one of the enabled_rerun_tools, or null,
  "reason": "concise explanation for the decision",
  "tool_call_args": {},
  "requires_review": true | false
}

Rules:
- "selected_tool" must be null unless "decision" is "call_tool".
- "requires_review" is only meaningful when "decision" is "finalize". Set it to true \
whenever the pillars disagree on direction, any pillar's status is not "ok", or you are \
finalizing only because you were told the loop guard was reached -- never ship an \
uncertain result silently.
- Only choose "call_tool" if another rerun of one pillar could plausibly resolve a \
genuine disagreement or fill a genuine gap, and tool_loop_count is below max_tool_loops."""


class LLMAgentError(Exception):
    """Raised when the LLM Agent could not be reached or returned an
    unparsable/invalid decision, and no fallback is available."""


def get_decision(context):
    """context: the reconciliation payload built by reconcile_and_decide
    (ticker, horizon, the three pillar results, pillar_status, errors,
    tool_loop_count, max_tool_loops, enabled_rerun_tools).

    Returns a dict matching the decision contract: decision, selected_tool,
    reason, tool_call_args, requires_review.
    """
    try:
        raw_text = _call_llm(context)
        return _parse_decision(raw_text)
    except Exception as exc:
        if not config.LLM_FALLBACK_ENABLED:
            raise LLMAgentError(str(exc)) from exc
        return _fallback_decision(context, reason=f"LLM Agent unavailable ({exc}); used deterministic fallback")


_OTHER_PROVIDER = {"openrouter": "ollama", "ollama": "openrouter"}


def call_llm_chat(system_prompt, user_prompt, timeout=None):
    """Shared chat call -- any caller's system/user prompt pair, routed to
    whichever provider config.LLM_PROVIDER selects.

    When config.LLM_PROVIDER_FALLBACK_ENABLED is True (the default), a
    failure on the primary provider (network error, non-2xx response --
    e.g. OpenRouter's free-tier daily rate limit, or a paid model with no
    credits) is not raised immediately: this automatically retries once
    against the *other* provider before giving up, so a temporary outage
    or quota exhaustion on one provider doesn't take down every LLM-driven
    capability in the project. Set LLM_PROVIDER_FALLBACK_ENABLED = False
    to disable this and raise on the primary provider's first failure,
    same as before this existed.

    Still raises (requests' usual exceptions, or a combined LLMAgentError
    naming both providers' failures if fallback was attempted) when no
    provider could serve the request -- callers decide how to handle that
    (get_decision/get_routing_decision fall back to a deterministic rule;
    see each module's own docstring). Raises ValueError if LLM_PROVIDER is
    neither "ollama" nor "openrouter".
    """
    primary = config.LLM_PROVIDER
    if primary not in _OTHER_PROVIDER:
        raise ValueError(f"unknown LLM_PROVIDER: {primary!r}")

    try:
        return _call_provider(primary, system_prompt, user_prompt, timeout)
    except Exception as primary_exc:
        if not config.LLM_PROVIDER_FALLBACK_ENABLED:
            raise
        secondary = _OTHER_PROVIDER[primary]
        try:
            return _call_provider(secondary, system_prompt, user_prompt, timeout)
        except Exception as secondary_exc:
            raise LLMAgentError(
                f"primary provider {primary!r} failed ({primary_exc}); "
                f"fallback provider {secondary!r} also failed ({secondary_exc})"
            ) from secondary_exc


def _call_provider(provider, system_prompt, user_prompt, timeout):
    if provider == "openrouter":
        return _call_openrouter_chat(system_prompt, user_prompt, timeout or config.OPENROUTER_TIMEOUT_SECONDS)
    return _call_ollama_chat(system_prompt, user_prompt, timeout or config.OLLAMA_TIMEOUT_SECONDS)


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
        f"technical_analysis: {json.dumps(context['technical_analysis'])}\n"
        f"fundamental_analysis: {json.dumps(context['fundamental_analysis'])}\n"
        f"sentiment_analysis: {json.dumps(context['sentiment_analysis'])}\n"
        f"pillar_status: {json.dumps(context['pillar_status'])}\n"
        f"errors: {json.dumps(context['errors'])}\n"
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


def _parse_decision(raw_text):
    decision = extract_json_object(raw_text)

    if decision.get("decision") not in ("finalize", "call_tool"):
        raise LLMAgentError(f"invalid decision value: {decision.get('decision')!r}")
    if decision["decision"] == "call_tool" and decision.get("selected_tool") not in config.ENABLED_RERUN_TOOLS:
        raise LLMAgentError(f"invalid selected_tool for call_tool: {decision.get('selected_tool')!r}")

    return {
        "decision": decision["decision"],
        "selected_tool": decision.get("selected_tool") if decision["decision"] == "call_tool" else None,
        "reason": decision.get("reason") or "",
        "tool_call_args": decision.get("tool_call_args") or {},
        "requires_review": bool(decision.get("requires_review", False)),
    }


def _fallback_decision(context, reason):
    """Deterministic stand-in for the LLM Agent when Ollama can't be
    reached or returns garbage. Never selects a rerun tool -- there's no
    reasoning available here to justify which pillar rerunning would
    help -- so it always finalizes, flagging requires_review whenever the
    pillars disagree or any pillar's status isn't "ok", matching the
    specification's own requires_review rule.
    """
    directions = {
        d
        for d in (
            ((context["technical_analysis"] or {}).get("technical_signal") or {}).get("direction"),
            ((context["fundamental_analysis"] or {}).get("composite") or {}).get("direction"),
            (context["sentiment_analysis"] or {}).get("direction"),
        )
        if d is not None
    }
    disagreement = len(directions) > 1
    any_unhealthy = any(status != "ok" for status in context["pillar_status"].values())

    return {
        "decision": "finalize",
        "selected_tool": None,
        "reason": reason,
        "tool_call_args": {},
        "requires_review": disagreement or any_unhealthy,
    }
