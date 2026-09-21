"""load_conversation_history — history-retrieval node.

Loads this user's most recent turns from "Memory".conversation_history
before parse_and_route runs, in parallel with load_user_memory (see
graph.py -- both only read `user_id`, so there's no ordering dependency
between them). Not consumed by anything yet: parse_and_route is still the
keyword-based placeholder described in its own docstring, with no
specification yet for using prior turns as context (e.g. resolving "what
about now?" against a ticker a previous turn established). Loaded
unconditionally anyway so a real classifier can start using it without
another round of graph wiring.

Returns an empty list -- not an error -- both when no history exists yet
for this user and when config.MEMORY_ENABLED is False, mirroring
load_user_memory's own graceful-degradation behavior.
"""

import psycopg2

from db.connection import get_connection

from ..config import MAX_HISTORY_TURNS, MEMORY_ENABLED


def load_conversation_history(state):
    if not MEMORY_ENABLED:
        return {"conversation_history": []}

    user_id = state.get("user_id")
    if not user_id:
        return {"conversation_history": []}

    try:
        conn = get_connection()
    except psycopg2.OperationalError:
        # A history-store hiccup shouldn't block routing -- degrade to no
        # history for this turn, same as a first-time user.
        return {"conversation_history": []}

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT message, intent, resolved_ticker, response, created_at
                FROM "Memory".conversation_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, MAX_HISTORY_TURNS),
            )
            rows = cur.fetchall()
    except psycopg2.Error:
        return {"conversation_history": []}
    finally:
        conn.close()

    # Query fetches newest-first (so LIMIT keeps the most recent turns);
    # reversed() here puts the returned window back in chronological
    # (oldest-first) order, the more natural shape for a caller to read.
    history = [
        {
            "message": message,
            "intent": intent,
            "resolved_ticker": resolved_ticker,
            "response": response,
            "created_at": created_at,
        }
        for message, intent, resolved_ticker, response, created_at in reversed(rows)
    ]
    return {"conversation_history": history}
