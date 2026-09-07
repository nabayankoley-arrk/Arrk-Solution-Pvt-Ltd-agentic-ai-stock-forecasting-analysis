"""update_user_memory — memory-persistence node (User Memory extension).

Thin adapter over agents.chat_intent_routing.nodes.update_user_memory's
shared implementation -- see that module for the watchlist
dedupe/cap/reorder and preference-merge logic. Wired in graph.py only on
the success path (build_final_response -> update_user_memory ->
persist_run), never after build_error_response: per that function's own
docstring, persisting memory for a turn that didn't produce a real
result is the base subgraph's call to make, not this node's.

The Orchestrator Subgraph has no NLU step of its own to populate
memory_update (e.g. detecting a stated preference in free text) -- that
belongs to the not-yet-implemented Chat Intent & Routing base subgraph's
parse_and_route. A caller may still supply memory_update directly
alongside ticker/horizon (see state.py); omitted, only the resolved
ticker is folded into the watchlist.
"""

from agents.chat_intent_routing.nodes.update_user_memory import update_user_memory as _update_user_memory


def update_user_memory(state):
    return _update_user_memory(
        {
            "user_id": state.get("user_id"),
            "user_memory": state.get("user_memory"),
            "resolved_ticker": state.get("ticker"),
            "memory_update": state.get("memory_update"),
        }
    )
