"""Tunable constants for the Chat Intent & Routing Subgraph and its User
Memory extension.

Both specification documents name their configurable parameters but fix no
numeric defaults ("No numeric defaults are fixed here; provide them
through deployment configuration.") -- every constant below is read from
the environment, falling back to this implementation's own default (not a
value taken from either specification) when unset.
"""

import os


def _env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


def _env_float(name, default):
    value = os.environ.get(name)
    return float(value) if value else default


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_tuple(name, default):
    value = os.environ.get(name)
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


# --- Base subgraph: parse_and_route / execute_tool_call ---

# Maximum number of agent -> tool -> agent iterations before the workflow
# is forced to a clarification response (loop guard; see graph.py's
# route_after_parse_and_route).
MAX_PARSE_LOOPS = _env_int("MAX_PARSE_LOOPS", 4)

# Minimum fuzzy-match confidence (0..1) for lookup_ticker to resolve a
# candidate company name automatically; below this, parse_and_route routes
# to clarification instead of guessing (see tools.lookup_ticker).
TICKER_MATCH_CONFIDENCE_THRESHOLD = _env_float("TICKER_MATCH_CONFIDENCE_THRESHOLD", 0.72)

# Maximum execution time (seconds) allowed for a selected tool. Deliberately
# much larger than the Orchestrator Subgraph's own TOOL_CALL_TIMEOUT_SECONDS
# (30s default) -- that one bounds a single pillar rerun, while
# invoke_orchestrator here runs a full three-pillar analysis (yfinance
# fetches, plus the Orchestrator's own reconcile_and_decide LLM call) end
# to end, a much larger unit of work.
#
# Raised from 120s after seeding real Fundamental Analysis data (see
# db/seed_fundamentals.py): once Technical and Fundamental can genuinely
# disagree (not just one of them erroring out), the Orchestrator's
# reconcile_and_decide can legitimately loop up to MAX_TOOL_LOOPS (3, see
# orchestrator/config.py) times trying to resolve that disagreement, each
# loop being its own LLM call. Measured against a local (Ollama) LLM
# Agent: a 3-loop run took ~200s -- 300s leaves real margin rather than
# sitting right at the observed worst case, since per-call latency varied
# considerably across testing (roughly 15-75s per single call alone).
TOOL_CALL_TIMEOUT_SECONDS = _env_int("TOOL_CALL_TIMEOUT_SECONDS", 300)

# Set of tools available to parse_and_route. A tool the LLM selects
# outside this set is treated the same as an unknown tool (see
# nodes/execute_tool_call.py).
ENABLED_TOOLS = _env_tuple(
    "ENABLED_TOOLS",
    ("lookup_ticker", "invoke_orchestrator", "invoke_single_pillar", "answer_general_question"),
)

VALID_PILLARS = ("technical", "fundamental", "sentiment")

# parse_and_route has no rule-based fallback that could plausibly stand in
# for entity extraction/intent classification (unlike the Orchestrator's
# reconcile_and_decide, "finalize vs. call_tool" has no equivalent safe
# default here) -- when the LLM Agent can't be reached or returns an
# unparsable/invalid decision, this controls whether parse_and_route
# degrades to a generic clarification question (True) or raises (False).
LLM_FALLBACK_ENABLED = _env_bool("LLM_FALLBACK_ENABLED", True)

# format_conversational_reply's own LLM call (turning a structured
# analysis result into prose) is NOT part of the "LLM Agent Decision
# Contract" parse_and_route needs an LLM for -- it's a well-defined
# structured-data-to-text task with a solid deterministic template
# available (see llm_client._fallback_conversational_reply). Given
# repeated observed unreliability (rate-limited/exhausted free API
# quotas, a local model echoing raw JSON back instead of writing prose),
# this defaults to skipping the LLM call entirely for that one step --
# every reply is then the deterministic template, always available,
# never wrong-shaped, and it removes one whole LLM call (and one whole
# failure point) from every completed analysis turn. Set to True once a
# reliably-available LLM is configured, for more natural/varied replies.
FORMAT_REPLY_USE_LLM = _env_bool("FORMAT_REPLY_USE_LLM", False)

# --- User Memory extension ---

# update_user_memory: watchlist cap -- oldest ticker dropped when exceeded.
MAX_WATCHLIST_SIZE = _env_int("MAX_WATCHLIST_SIZE", 10)

# load_user_memory / update_user_memory: on/off switch. When False,
# load_user_memory returns an empty memory object regardless of what's
# stored (so parse_and_route behaves exactly as the base subgraph without
# this extension) and update_user_memory no-ops -- letting the extension
# be disabled without changing the base subgraph, per the specification's
# Architecture section.
MEMORY_ENABLED = _env_bool("MEMORY_ENABLED", True)

# --- Session continuity (conversation_sessions / conversation_messages) ---
# Not named by either specification document as a "configurable
# parameter", but needed for the same reason MEMORY_ENABLED exists: lets
# the conversation_sessions/conversation_messages persistence (see
# nodes/load_conversation_context.py, nodes/update_session_context.py) be
# turned off -- e.g. for a stateless smoke test -- without changing graph
# wiring.
SESSION_CONTINUITY_ENABLED = _env_bool("SESSION_CONTINUITY_ENABLED", True)

# How many most-recent conversation_messages rows to hydrate into
# conversation_history when a caller doesn't supply one (see
# load_conversation_context.py). Keeps the LLM prompt bounded for a very
# long-running session.
MAX_HISTORY_MESSAGES = _env_int("MAX_HISTORY_MESSAGES", 20)
