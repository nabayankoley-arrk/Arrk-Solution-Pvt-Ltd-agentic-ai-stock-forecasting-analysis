"""update_user_memory — memory-persistence node.

Saves what should be remembered from this turn: `resolved_ticker` is
moved to the front of the watchlist (de-duplicated, capped at
MAX_WATCHLIST_SIZE -- oldest dropped when exceeded, per the
specification), and any preference `memory_update` supplies (e.g. a
stated default horizon) is merged into the user's existing preferences.
No-ops on its own (watchlist unchanged) when resolved_ticker is None, so
graph.py runs this node unconditionally on every turn -- see that
module's docstring for why that's fine even on the out_of_scope path.

A save failure here is logged and swallowed rather than raised: by the
time this node runs, `response` has already been computed (see
route_to_orchestrator.py/handle_out_of_scope.py) -- a transient memory-
store hiccup shouldn't cost the caller the answer they're actually
waiting for.

Wired into this package's own graph.py as the last node before END. The
Orchestrator Subgraph (agents/orchestrator) no longer has a node like this
of its own -- see that package's graph.py for the split.
"""

import psycopg2

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
    try:
        save_user_memory(user_id, updated_memory)
    except psycopg2.Error as exc:
        print(f"update_user_memory: failed to persist watchlist/preferences for user_id={user_id}: {exc}")
    return {"updated_memory": updated_memory}
