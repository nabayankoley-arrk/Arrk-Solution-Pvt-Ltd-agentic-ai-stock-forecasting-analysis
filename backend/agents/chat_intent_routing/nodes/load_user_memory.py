"""load_user_memory — memory-retrieval node.

Loads the user's saved watchlist and preferences from
"Memory".user_memory before parse_and_route runs, so it can resolve a
missing ticker from the watchlist instead of always asking for
clarification (see the specification's "Memory-Informed Routing" core
component). Returns an empty memory object -- not an error -- both when
no row exists yet for this user (a first-time user is a normal case, not
a failure) and when config.MEMORY_ENABLED is False, so parse_and_route
never has to branch on whether memory is active.

Wired into this package's own graph.py as the first node after START. The
Orchestrator Subgraph (agents/orchestrator) no longer has a node like this
of its own -- see that package's graph.py for the split.
"""

import psycopg2

from db.connection import get_connection

from ..config import MEMORY_ENABLED

_EMPTY_MEMORY = {"watchlist": [], "preferences": {}}


def load_user_memory(state):
    if not MEMORY_ENABLED:
        return {"user_memory": dict(_EMPTY_MEMORY)}

    user_id = state.get("user_id")
    if not user_id:
        return {"user_memory": dict(_EMPTY_MEMORY)}

    try:
        conn = get_connection()
    except psycopg2.OperationalError:
        # A memory-store hiccup shouldn't block routing -- degrade to no
        # memory for this turn, same as a first-time user.
        return {"user_memory": dict(_EMPTY_MEMORY)}

    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT watchlist, preferences FROM "Memory".user_memory WHERE user_id = %s',
                (user_id,),
            )
            row = cur.fetchone()
    except psycopg2.Error:
        return {"user_memory": dict(_EMPTY_MEMORY)}
    finally:
        conn.close()

    if row is None:
        return {"user_memory": dict(_EMPTY_MEMORY)}

    watchlist, preferences = row
    return {"user_memory": {"watchlist": watchlist or [], "preferences": preferences or {}}}
