"""update_user_memory — memory-persistence node.

Saves what should be remembered from this turn: `resolved_ticker` is
moved to the front of the watchlist (de-duplicated, capped at
MAX_WATCHLIST_SIZE -- oldest dropped when exceeded, per the
specification), and any preference `memory_update` supplies (e.g. a
stated default horizon) is merged into the user's existing preferences.
Per the specification's Edges section, this only runs after a normal
completed response -- routing clarification/out-of-scope turns around
this node entirely is the base subgraph's responsibility, not enforced
here.

Not yet wired into this package's own (not-yet-implemented) base graph --
see this package's __init__.py -- but is wired into
agents/orchestrator/graph.py via that package's own
nodes/update_user_memory.py adapter.
"""

from db.upsert import save_user_memory

from ..config import MAX_WATCHLIST_SIZE, MEMORY_ENABLED


def update_user_memory(state):
    if not MEMORY_ENABLED:
        return {"updated_memory": None}

    user_id = state.get("user_id")
    if not user_id:
        return {"updated_memory": None}

    current_memory = state.get("user_memory") or {"watchlist": [], "preferences": {}}
    resolved_ticker = state.get("resolved_ticker")
    memory_update = state.get("memory_update") or {}

    watchlist = [t for t in (current_memory.get("watchlist") or []) if t != resolved_ticker]
    if resolved_ticker:
        watchlist.insert(0, resolved_ticker)
    watchlist = watchlist[:MAX_WATCHLIST_SIZE]

    preferences = dict(current_memory.get("preferences") or {})
    preferences.update(memory_update.get("preferences") or {})

    updated_memory = {"watchlist": watchlist, "preferences": preferences}
    save_user_memory(user_id, updated_memory)
    return {"updated_memory": updated_memory}
