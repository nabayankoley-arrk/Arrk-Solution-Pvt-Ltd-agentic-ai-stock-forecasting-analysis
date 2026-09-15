"""Tunable constants for the Chat Intent & Routing subgraph.

The "User Memory — Specification (Chat Intent & Routing Subgraph
Extension)" document names two configurable parameters (MAX_WATCHLIST_SIZE,
MEMORY_ENABLED) with no numeric/boolean default given -- these, and
MAX_HISTORY_TURNS below (not part of that specification), are read from
the environment, falling back to this implementation's own default when
unset.
"""

import os


def _env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --- update_user_memory: watchlist cap ---
MAX_WATCHLIST_SIZE = _env_int("MAX_WATCHLIST_SIZE", 10)

# --- load_conversation_history: how many past turns to load per call ---
MAX_HISTORY_TURNS = _env_int("MAX_HISTORY_TURNS", 20)

# --- load_user_memory / update_user_memory: on/off switch ---
# When False, load_user_memory returns an empty memory object regardless
# of what's stored (so parse_and_route behaves exactly as if no memory
# were configured) and update_user_memory no-ops -- letting memory be
# disabled without changing any other node, per the specification's
# Architecture section.
MEMORY_ENABLED = _env_bool("MEMORY_ENABLED", True)


# --- parse_and_route: minimal keyword-based stock-market intent detection ---
# No NLU specification exists yet for this subgraph's intent classifier
# (see __init__.py) -- this is a deliberately simple placeholder. A
# resolved ticker (explicit, extracted, or from the watchlist) or one of
# these keywords anywhere in `message` (case-insensitive) is enough to
# route to the Orchestrator Subgraph; everything else is 'out_of_scope'.
# Swap this for a real classifier (rule-based or LLM-driven) without
# touching any other node's contract -- see nodes/parse_and_route.py.
STOCK_KEYWORDS = (
    "stock", "share", "shares", "price", "forecast", "market", "buy", "sell",
    "invest", "trend", "chart", "technical", "fundamental", "target",
    "stop loss", "stoploss", "analysis", "valuation", "earnings",
)

# --- handle_out_of_scope ---
# The one fixed response returned for every 'out_of_scope' query (see
# nodes/handle_out_of_scope.py) -- this application only answers
# stock/market analysis questions, so no other topic is ever answered,
# regardless of what's asked.
OUT_OF_SCOPE_MESSAGE = (
    "I can only help with stock and market questions -- try asking about a "
    "specific ticker's price, trend, or forecast."
)
