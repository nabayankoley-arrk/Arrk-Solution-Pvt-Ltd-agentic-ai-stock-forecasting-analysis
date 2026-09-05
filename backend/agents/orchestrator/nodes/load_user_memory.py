"""load_user_memory — memory-retrieval node (User Memory extension).

Thin adapter over agents.chat_intent_routing.nodes.load_user_memory's
shared implementation, so the Orchestrator Subgraph doesn't duplicate its
DB access / graceful-degradation logic (empty memory on a missing
user_id, config.MEMORY_ENABLED=False, or a DB hiccup -- see that
module's docstring). Runs first, before validate_input, so validate_input
can fall back to the caller's saved watchlist when no ticker was
supplied (see validate_input.py).
"""

from agents.chat_intent_routing.nodes.load_user_memory import load_user_memory as _load_user_memory


def load_user_memory(state):
    return _load_user_memory(state)
