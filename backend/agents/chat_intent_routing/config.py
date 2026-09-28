"""Tunable constants for the Chat Intent & Routing subgraph.

MEMORY_ENABLED, MAX_HISTORY_MESSAGES and MAX_TOOL_ROUNDS are read from the
environment, falling back to the defaults below when unset.
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import os


def _env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# --- persist_conversation_turn: on/off switch for the audit log ---
MEMORY_ENABLED = _env_bool("MEMORY_ENABLED", True)


# --- agent: how many past messages (user, assistant, tool) go into a prompt ---
MAX_HISTORY_MESSAGES = _env_int("MAX_HISTORY_MESSAGES", 20)

# --- agent: rounds of tool calls allowed per turn before it must answer ---
MAX_TOOL_ROUNDS = _env_int("MAX_TOOL_ROUNDS", 3)

# --- replies used when an LLM or the Orchestrator fails ---
UNAVAILABLE_REPLY = "The assistant is temporarily unavailable -- please try again in a moment."
ERROR_REPLY = "Something went wrong processing that request."
