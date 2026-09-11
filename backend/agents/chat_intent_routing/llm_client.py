"""LLM Agent client for parse_and_route (and the other two small LLM
calls this subgraph needs: format_conversational_reply and the
answer_general_question tool).

Reuses agents.orchestrator.llm_client's provider plumbing
(call_llm_chat/extract_json_object, Ollama/OpenRouter selection via
agents.orchestrator.config) rather than duplicating it -- that module's
own docstring says call_llm_chat/extract_json_object are "exported for
reuse by other LLM-driven capabilities", and agents/orchestrator's own
forecast_price_range.py already does exactly this within the same
package. One LLM Agent backend for the whole project, just different
system prompts/output shapes per caller.

Like reconcile_and_decide's get_decision(), get_routing_decision() prompts
the model for one JSON object matching the specification's "LLM Agent
Decision Contract" rather than depending on a given model's function-
calling support (inconsistent across the free/cheap models this is meant
to run against).
"""

import json

from ..orchestrator.llm_client import LLMAgentError, call_llm_chat, extract_json_object
from .config import ENABLED_TOOLS, FORMAT_REPLY_USE_LLM, LLM_FALLBACK_ENABLED, VALID_PILLARS

_ROUTING_SYSTEM_PROMPT = f"""You are the Chat Intent & Routing agent for a stock-analysis platform. You turn a \
free-text chat message (plus conversation history and any known session/user context) into a routing decision. \
You are the ONLY decision-making component in this subgraph -- tool execution, response formatting, and \
persistence are deterministic steps that run around your decision.

Enabled tools: {json.dumps(list(ENABLED_TOOLS))}
- lookup_ticker(candidate_name): fuzzy-matches a company name against the tracked universe.
- invoke_orchestrator(ticker, horizon): the full three-pillar Technical + Fundamental + Sentiment analysis.
- invoke_single_pillar(ticker, pillar_name, params): direct call to one pillar only
  (pillar_name one of {json.dumps(list(VALID_PILLARS))}), when the user's question narrows to just one concern
  (e.g. "what's the RSI on X" -> technical only; skips reconciliation since there's nothing to reconcile with a
  single source).
- answer_general_question(question): a plain educational answer, never touching an analysis pillar.

Respond with ONLY a single JSON object, no other text, matching this shape:
{{
  "action": "tool_call" | "clarify" | "out_of_scope" | "finalize",
  "selected_tool": "lookup_ticker" | "invoke_orchestrator" | "invoke_single_pillar" | "answer_general_question" | null,
  "tool_call_args": {{}},
  "clarification_question": "string, required when action == clarify" | null,
  "out_of_scope_reason": "string, required when action == out_of_scope" | null,
  "resolved_ticker": "string ticker symbol, or null if not yet known",
  "resolved_horizon": "short_term" | "medium_term" | "long_term" | null,
  "resolved_scope": ["technical", "fundamental", "sentiment"] subset, or null if not yet narrowed,
  "memory_update": {{"preferences": {{}}}} | null
}}

Rules:
- A chat message is never structurally "invalid" the way a malformed ticker parameter would be -- nonsense or
  off-topic input should be classified "out_of_scope", not treated as an error.
- Use "tool_call" only when selected_tool is one of the enabled tools above and you have enough information to
  call it usefully (e.g. don't call invoke_orchestrator with a ticker you are not reasonably confident about --
  call lookup_ticker first, or ask for clarification instead of guessing).
- NEVER call lookup_ticker again once parsed_entities below already shows a ticker_lookup result with a non-null
  "match" for the ticker you're working with -- that ticker is already resolved. Immediately proceed to
  invoke_orchestrator (or invoke_single_pillar, if resolved_scope narrows to one pillar) instead.
- Use "clarify" when the ticker is ambiguous or a required detail (e.g. which company) is missing -- end the turn
  with a targeted question rather than guessing.
- Use "out_of_scope" for an untracked ticker, a general/educational question better served by
  answer_general_question, or chit-chat that isn't an analyzable ticker request -- but prefer calling
  answer_general_question (a tool_call) over an out_of_scope decline when the question is genuinely educational
  and answerable without live data.
- Use "finalize" ONLY when downstream_result below already holds the result of an invoke_orchestrator or
  invoke_single_pillar call you made earlier in this same turn -- you are then just confirming you're ready to
  have that analysis formatted into a conversational reply.
- If downstream_result below already holds the result of an answer_general_question call instead, respond with
  action "out_of_scope" and an out_of_scope_reason noting it was a general question -- general answers are
  delivered as a plain answer, not run through analysis-result formatting, even though the tool call itself
  succeeded.
- If a prior turn's resolved ticker/horizon/scope or a saved watchlist is given below and this message is a
  natural follow-up (e.g. "how's it looking today?", "what about the fundamentals?"), reuse that context instead
  of asking the user to repeat themselves.
- If the user states a lasting preference (e.g. "always show me the long term view"), set memory_update
  accordingly; otherwise leave it null."""

_GENERAL_QUESTION_SYSTEM_PROMPT = (
    "You are a helpful assistant answering a general/educational question about investing or financial markets "
    "for a stock-analysis chat application. Do not fabricate real-time prices, news, or analysis for a specific "
    "ticker -- if the question actually requires that, say so plainly instead of guessing. Keep the answer "
    "concise and in plain language."
)

_FORMAT_REPLY_SYSTEM_PROMPT = (
    "You turn a structured stock-analysis result (technical/fundamental/sentiment signals, a decision, risk "
    "flags) into a short, conversational chat reply. Surface the narrative and the key highlights -- direction, "
    "the one or two most important signals, and any risk flags -- rather than dumping the raw structured data. "
    "Offer to go into more detail rather than front-loading everything. Do not invent numbers not present in the "
    "given data.\n\n"
    "Your entire response must be plain conversational English prose -- ordinary sentences a person would read "
    "in a chat app. NEVER output JSON, a code block, curly braces, or any part of the input data structure "
    "verbatim -- restating the input as-is is not an acceptable answer, even if wrapped in a sentence."
)


def get_routing_decision(context):
    """context: raw_message, conversation_history, session_context,
    user_memory, parsed_entities, downstream_result, requery_count.

    Returns a dict matching the decision contract: action, selected_tool,
    tool_call_args, clarification_question, out_of_scope_reason,
    resolved_ticker, resolved_horizon, resolved_scope, memory_update.
    """
    try:
        raw_text = call_llm_chat(_ROUTING_SYSTEM_PROMPT, _build_routing_prompt(context))
        return _parse_routing_decision(raw_text)
    except Exception as exc:
        if not LLM_FALLBACK_ENABLED:
            raise LLMAgentError(str(exc)) from exc
        return _fallback_routing_decision(reason=f"LLM Agent unavailable ({exc}); used deterministic fallback")


def answer_general_question(question):
    """Plain LLM completion for the answer_general_question tool. Raises
    on failure -- there is no sensible non-LLM fallback for an open
    educational question -- callers (tools.py) decide how to surface
    that as a tool result.
    """
    return call_llm_chat(_GENERAL_QUESTION_SYSTEM_PROMPT, question)


def format_conversational_reply(downstream_result):
    """Turns a structured analysis result into a conversational reply.

    Skips the LLM entirely by default (config.FORMAT_REPLY_USE_LLM =
    False) and always uses the deterministic template instead -- this is
    a well-defined structured-data-to-text task, not the free-text
    entity-extraction/intent-classification job parse_and_route actually
    needs an LLM for, and repeated testing found this specific call to be
    the least reliable one in the whole subgraph (rate-limited/exhausted
    free-tier quotas, and a local model that echoed the raw JSON input
    back verbatim instead of writing prose). Removing it removes an
    entire failure point and one whole LLM call from every completed
    analysis turn, with no loss of correctness -- see
    _fallback_conversational_reply's own docstring for the shapes it
    handles.

    Set config.FORMAT_REPLY_USE_LLM = True for more natural/varied
    replies once a reliably-available LLM is configured; the same
    degenerate-output detection (_looks_like_raw_json_echo) and
    exception handling still guard that path.
    """
    if not FORMAT_REPLY_USE_LLM:
        return _fallback_conversational_reply(downstream_result)

    try:
        raw_text = call_llm_chat(_FORMAT_REPLY_SYSTEM_PROMPT, json.dumps(downstream_result, default=str))
        if _looks_like_raw_json_echo(raw_text):
            return _fallback_conversational_reply(downstream_result)
        return raw_text
    except Exception:
        return _fallback_conversational_reply(downstream_result)


def _looks_like_raw_json_echo(raw_text):
    stripped = (raw_text or "").strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        return False
    try:
        json.loads(stripped)
    except (ValueError, TypeError):
        return False
    return True


def _build_routing_prompt(context):
    return (
        f"raw_message: {context.get('raw_message')!r}\n"
        f"conversation_history: {json.dumps(context.get('conversation_history') or [])}\n"
        f"session_context (last resolved ticker/horizon/scope, if any): "
        f"{json.dumps(context.get('session_context') or {})}\n"
        f"user_memory (watchlist/preferences, if any): {json.dumps(context.get('user_memory') or {})}\n"
        f"parsed_entities so far this turn: {json.dumps(context.get('parsed_entities') or {})}\n"
        f"downstream_result (a tool's result, if one was already called this turn): "
        f"{json.dumps(context.get('downstream_result'))}\n"
        f"requery_count: {context.get('requery_count', 0)}\n"
    )


def _parse_routing_decision(raw_text):
    decision = extract_json_object(raw_text)

    action = decision.get("action")
    if action not in ("tool_call", "clarify", "out_of_scope", "finalize"):
        raise LLMAgentError(f"invalid action: {action!r}")

    selected_tool = decision.get("selected_tool") if action == "tool_call" else None
    if action == "tool_call" and selected_tool not in ENABLED_TOOLS:
        raise LLMAgentError(f"invalid or disabled selected_tool for tool_call: {selected_tool!r}")

    if action == "clarify" and not decision.get("clarification_question"):
        raise LLMAgentError("clarification_question is required when action == clarify")

    if action == "out_of_scope" and not decision.get("out_of_scope_reason"):
        raise LLMAgentError("out_of_scope_reason is required when action == out_of_scope")

    resolved_scope = decision.get("resolved_scope")
    if resolved_scope is not None and not (
        isinstance(resolved_scope, list) and all(p in VALID_PILLARS for p in resolved_scope)
    ):
        raise LLMAgentError(f"invalid resolved_scope: {resolved_scope!r}")

    return {
        "action": action,
        "selected_tool": selected_tool,
        "tool_call_args": decision.get("tool_call_args") or {},
        "clarification_question": decision.get("clarification_question") if action == "clarify" else None,
        "out_of_scope_reason": decision.get("out_of_scope_reason") if action == "out_of_scope" else None,
        "resolved_ticker": decision.get("resolved_ticker") or None,
        "resolved_horizon": decision.get("resolved_horizon") or None,
        "resolved_scope": resolved_scope,
        "memory_update": decision.get("memory_update") or None,
    }


def _fallback_routing_decision(reason):
    """Deterministic stand-in for parse_and_route when the LLM Agent
    can't be reached or returns garbage. Unlike reconcile_and_decide's
    fallback, there is no rule-based way to extract entities or classify
    intent from free text -- so this always asks the user to clarify
    (the safest non-guessing default) rather than risking a wrong ticker
    or an incorrect out-of-scope decline. See config.LLM_FALLBACK_ENABLED.
    """
    return {
        "action": "clarify",
        "selected_tool": None,
        "tool_call_args": {},
        "clarification_question": (
            "I couldn't process that just now -- could you tell me the ticker symbol and what you'd like to "
            "know (e.g. technical, fundamental, or overall analysis)?"
        ),
        "out_of_scope_reason": None,
        "resolved_ticker": None,
        "resolved_horizon": None,
        "resolved_scope": None,
        "memory_update": None,
        "fallback_reason": reason,
    }


def _fallback_conversational_reply(downstream_result):
    """Deterministic template used when the LLM call fails, or "succeeds"
    but just echoes the input JSON back (see format_conversational_reply
    above). downstream_result here is whatever payload was actually
    handed to the LLM -- format_conversational_reply.py's node already
    unwraps invoke_single_pillar's {"pillar", "ticker", "status",
    "result"} wrapper down to just the pillar's own result dict before
    calling this, so this must be able to read *any* of the shapes that
    can arrive:
      - Orchestrator final_response: "technical_summary"/"fundamental_summary"/
        "sentiment_summary" siblings, top-level "risk_flags"/"narrative".
        Its top-level "decision" is NOT a market signal -- it's the
        Orchestrator's own internal control-flow field ("finalize" |
        "call_tool", per reconcile_and_decide's own decision contract) and
        must NOT be read as one (a previous version of this function did
        exactly that, producing "Overall signal: finalize." -- nonsense
        -- observed in testing).
      - Technical Analysis result: direction nested under
        "technical_signal".
      - Fundamental Analysis result: direction/confidence/risk_flags
        nested under "composite".
      - Sentiment Analysis result: top-level "direction"/"confidence"
        directly (see agents/orchestrator/nodes/_pillar_runners.py's
        run_sentiment stub shape).
    """
    if not downstream_result:
        return "I don't have a result to share for that yet."

    ticker = downstream_result.get("ticker")
    is_orchestrator_shape = (
        "technical_summary" in downstream_result
        or "fundamental_summary" in downstream_result
        or "sentiment_summary" in downstream_result
    )

    if is_orchestrator_shape:
        technical = downstream_result.get("technical_summary") or {}
        fundamental = downstream_result.get("fundamental_summary") or {}
        sentiment = downstream_result.get("sentiment_summary") or {}
        fundamental_composite = fundamental.get("composite") or {}

        direction = (
            (technical.get("technical_signal") or {}).get("direction")
            or fundamental_composite.get("direction")
            or sentiment.get("direction")
        )
        confidence = technical.get("confidence")
        if confidence is None:
            confidence = fundamental_composite.get("confidence")
        support_resistance = technical.get("support_resistance") or {}
        current_price = technical.get("current_price")
        risk_flags = downstream_result.get("risk_flags") or []
        narrative = downstream_result.get("narrative")
    else:
        technical_signal = downstream_result.get("technical_signal") or {}
        composite = downstream_result.get("composite") or {}

        direction = downstream_result.get("direction") or technical_signal.get("direction") or composite.get("direction")
        confidence = downstream_result.get("confidence")
        if confidence is None:
            confidence = composite.get("confidence")
        support_resistance = downstream_result.get("support_resistance") or {}
        current_price = downstream_result.get("current_price")
        risk_flags = downstream_result.get("risk_flags") or composite.get("risk_flags") or []
        narrative = None

    support = support_resistance.get("support")
    resistance = support_resistance.get("resistance")

    parts = [f"Here's what I found for {ticker}:" if ticker else "Here's what I found:"]
    if current_price is not None:
        parts.append(f"Current price: {current_price}.")
    if direction:
        parts.append(f"Overall signal: {direction}.")
    if confidence is not None:
        parts.append(f"Confidence: {confidence}.")
    if support is not None and resistance is not None:
        parts.append(f"Support around {support}, resistance around {resistance}.")
    if risk_flags:
        parts.append(f"Flags to note: {', '.join(str(f) for f in risk_flags[:3])}.")
    if narrative:
        parts.append(f"Note: {narrative}")
    if len(parts) == 1:
        parts.append("The underlying data didn't have a clear signal to summarize.")
    parts.append("Ask if you'd like more detail on any part of this.")
    return " ".join(parts)


__all__ = ["get_routing_decision", "answer_general_question", "format_conversational_reply"]
