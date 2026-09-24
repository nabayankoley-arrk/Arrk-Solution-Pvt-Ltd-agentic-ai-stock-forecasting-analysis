"""Tunable constants for the Chat Intent & Routing subgraph.

MEMORY_ENABLED and MAX_HISTORY_TURNS are read from the environment, falling
back to the defaults below when unset.
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


# --- interpret / respond: how many past turns (user + assistant) go into a prompt ---
MAX_HISTORY_TURNS = _env_int("MAX_HISTORY_TURNS", 6)

# --- replies used when an LLM or the Orchestrator fails ---
UNAVAILABLE_REPLY = "The assistant is temporarily unavailable -- please try again in a moment."
ERROR_REPLY = "Something went wrong processing that request."
