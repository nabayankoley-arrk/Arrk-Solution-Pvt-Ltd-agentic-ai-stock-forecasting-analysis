"""parse_and_route — the single LLM agent node and only decision-making
component in this subgraph, per the specification's Architecture section.

Extracts entities from raw_message + conversation_history (plus session
and user-memory context so it can resolve a follow-up like "how's it
looking today?" without re-asking), and decides whether to call a tool,
ask a clarifying question, decline as out of scope, or finalize.

Reads: raw_message, conversation_history, parsed_entities,
downstream_result (if returning from a tool call), session_context,
user_memory. Writes: parsed_entities, resolved_ticker, resolved_horizon,
resolved_scope, routing_decision, clarification_question,
out_of_scope_reason, selected_tool, tool_call_args, memory_update.

requery_count is NOT incremented here -- per the specification,
execute_tool_call owns that counter (it only advances once per actual
tool call, not per parse_and_route pass).

Deterministic fast path (_try_deterministic_route, below): NOT part of
either specification document, which frames the LLM Agent as the sole
decision-maker. Added after repeated, reproducible testing showed the
free/local LLM options this project has access to (an exhausted
OpenRouter free-tier daily quota, and a slow/unreliable local 3B Ollama
model) cannot reliably or promptly classify even an unambiguous request
like "how is INFY.NS looking?" -- sometimes looping, sometimes asking a
confused clarifying question for a ticker it already resolved, sometimes
taking 15-60+ seconds per call. A message that plainly names a tracked
ticker is not actually an ambiguous natural-language-understanding
problem; tools.lookup_ticker's own token-level matching (already needed
for the lookup_ticker tool itself) can resolve it deterministically,
instantly, with zero dependency on which LLM provider is currently
available. This is tried FIRST, on the initial pass only (never mid-loop,
so it can't interfere with a tool result already in progress); it only
short-circuits the turn when it can resolve a ticker with confidence --
anything else (a follow-up referencing session context without repeating
the ticker, an ambiguous/untracked name, a general question, chit-chat)
still falls through to the LLM exactly as before.
"""

import re

from .. import tools
from ..llm_client import get_routing_decision

_PILLAR_KEYWORDS = {
    "technical": ("technical", "chart", "trend", "momentum", "rsi", "moving average", "support", "resistance"),
    "fundamental": ("fundamental", "valuation", "pe ratio", "p/e", "earnings", "balance sheet", "financials"),
    "sentiment": ("sentiment", "news", "buzz"),
}
_SHORT_TERM_RE = re.compile(r"\b\d+\s*(day|days)\b", re.IGNORECASE)
_LONG_TERM_WORDS = ("year", "years", "long term", "long-term")


def parse_and_route(state):
    previous_parsed_entities = state.get("parsed_entities") or {}
    downstream_result = state.get("downstream_result")
    is_first_pass = state.get("requery_count", 0) == 0 and downstream_result is None and not previous_parsed_entities

    if downstream_result is not None and state.get("selected_tool") in ("invoke_orchestrator", "invoke_single_pillar"):
        # An analysis tool already ran and returned a result (success or
        # error -- format_conversational_reply.py handles an "error" key
        # gracefully either way). Whether to "finalize" here has no
        # genuine judgment call left to make -- there is nothing else to
        # try -- so this skips the second LLM round-trip the specification
        # would otherwise spend confirming exactly that. Same reliability
        # rationale as _try_deterministic_route below.
        decision = _finalize_decision()
    elif is_first_pass:
        decision = _try_deterministic_route(state.get("raw_message"))
    else:
        decision = None

    if decision is None:
        context = {
            "raw_message": state.get("raw_message"),
            "conversation_history": state.get("conversation_history") or [],
            "session_context": state.get("session_context"),
            "user_memory": state.get("user_memory"),
            "parsed_entities": previous_parsed_entities,
            "downstream_result": state.get("downstream_result"),
            "requery_count": state.get("requery_count", 0),
        }
        decision = get_routing_decision(context)

    resolved_ticker = decision["resolved_ticker"] or state.get("resolved_ticker")
    resolved_horizon = decision["resolved_horizon"] or state.get("resolved_horizon")
    resolved_scope = decision["resolved_scope"] if decision["resolved_scope"] is not None else state.get("resolved_scope")

    # Carries ticker_lookup (set by execute_tool_call after a lookup_ticker
    # call) forward instead of dropping it -- both so the LLM keeps seeing
    # it in later prompts within the same loop, and so
    # _resolve_stuck_lookup_loop below can see it too.
    parsed_entities = dict(previous_parsed_entities)
    parsed_entities["candidate_ticker"] = resolved_ticker
    parsed_entities["horizon_text"] = resolved_horizon
    parsed_entities["scope_guess"] = resolved_scope

    selected_tool, tool_call_args = _resolve_stuck_lookup_loop(
        decision["action"], decision["selected_tool"], decision["tool_call_args"], parsed_entities, resolved_ticker, resolved_horizon, resolved_scope
    )

    return {
        "parsed_entities": parsed_entities,
        "resolved_ticker": resolved_ticker,
        "resolved_horizon": resolved_horizon,
        "resolved_scope": resolved_scope,
        "routing_decision": decision["action"],
        "selected_tool": selected_tool,
        "tool_call_args": tool_call_args,
        "clarification_question": decision["clarification_question"],
        "out_of_scope_reason": decision["out_of_scope_reason"],
        "memory_update": decision["memory_update"] or state.get("memory_update"),
    }


def _finalize_decision():
    """A decision dict with action="finalize" and every other field None
    -- resolved_ticker/horizon/scope come out as None here deliberately,
    since parse_and_route's caller (the code just above) always falls
    back to state's own already-resolved values (`decision["resolved_ticker"]
    or state.get("resolved_ticker")`, etc.) when a decision doesn't set
    them itself, so nothing is lost.
    """
    return {
        "action": "finalize",
        "selected_tool": None,
        "tool_call_args": {},
        "clarification_question": None,
        "out_of_scope_reason": None,
        "resolved_ticker": None,
        "resolved_horizon": None,
        "resolved_scope": None,
        "memory_update": None,
    }


def _try_deterministic_route(raw_message):
    """Returns a decision dict matching get_routing_decision's contract,
    or None to fall through to the LLM. See this module's docstring for
    why this exists.

    Only engages when tools.lookup_ticker (whole-word/token matching
    against the tracked universe -- see that function's own docstring)
    resolves raw_message to exactly one confident ticker match. An
    ambiguous or missing ticker returns None deliberately -- clarifying
    or classifying out-of-scope in that case still needs the LLM's
    judgment, not a guess.
    """
    if not raw_message or not isinstance(raw_message, str):
        return None

    lookup_result = tools.lookup_ticker(raw_message)
    ticker = lookup_result.get("match")
    if not ticker:
        return None

    lowered = raw_message.lower()
    scope = [pillar for pillar, keywords in _PILLAR_KEYWORDS.items() if any(k in lowered for k in keywords)] or None

    horizon = None
    if _SHORT_TERM_RE.search(lowered):
        horizon = "short_term"
    elif any(w in lowered for w in _LONG_TERM_WORDS):
        horizon = "long_term"

    if scope and len(scope) == 1:
        selected_tool = "invoke_single_pillar"
        tool_call_args = {"ticker": ticker, "pillar_name": scope[0], "params": {"horizon": horizon}}
    else:
        selected_tool = "invoke_orchestrator"
        tool_call_args = {"ticker": ticker, "horizon": horizon}

    return {
        "action": "tool_call",
        "selected_tool": selected_tool,
        "tool_call_args": tool_call_args,
        "clarification_question": None,
        "out_of_scope_reason": None,
        "resolved_ticker": ticker,
        "resolved_horizon": horizon,
        "resolved_scope": scope,
        "memory_update": None,
    }


def _resolve_stuck_lookup_loop(action, selected_tool, tool_call_args, parsed_entities, resolved_ticker, resolved_horizon, resolved_scope):
    """Deterministic guard against a real, observed failure mode with
    smaller/weaker LLMs (e.g. a local 3B model via Ollama): the model
    re-selects lookup_ticker on a later loop iteration even though a
    prior lookup_ticker call already returned a confident match for the
    same ticker (visible in parsed_entities["ticker_lookup"], which this
    node now carries forward instead of dropping each pass -- see above).
    Left alone, this burns through MAX_PARSE_LOOPS and ends in a
    clarification question for a request that was already resolvable.

    Not part of either specification document -- the specification
    assumes parse_and_route reliably notices its own prior tool result;
    this is a safety net for when it doesn't, the same way
    reconcile_and_decide's deterministic fallback and the loop guard
    itself are safety nets around LLM unreliability elsewhere in this
    project.
    """
    if action != "tool_call" or selected_tool != "lookup_ticker":
        return selected_tool, tool_call_args

    ticker_lookup = parsed_entities.get("ticker_lookup") or {}
    if not resolved_ticker or ticker_lookup.get("match") != resolved_ticker:
        return selected_tool, tool_call_args

    # The ticker is already confidently resolved -- move on to an actual
    # analysis tool instead of looking it up again.
    if resolved_scope and len(resolved_scope) == 1:
        return "invoke_single_pillar", {
            "ticker": resolved_ticker,
            "pillar_name": resolved_scope[0],
            "params": {"horizon": resolved_horizon},
        }
    return "invoke_orchestrator", {"ticker": resolved_ticker, "horizon": resolved_horizon}
