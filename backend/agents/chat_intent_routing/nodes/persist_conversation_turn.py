"""persist_conversation_turn — history-persistence node.

Appends this turn (the caller's message and the response this graph
produced) to "Memory".conversation_history, in parallel with
update_user_memory (see graph.py -- both branches feed both nodes, and
neither reads the other's output). Runs regardless of which intent branch
executed, same reasoning as update_user_memory's own unconditional wiring:
an out_of_scope turn is still worth remembering as context for a later
one, even though it updates no watchlist.

No-ops when there's no user_id, same as update_user_memory, since there's
nothing to key the row on. Unlike "Memory".user_memory (one row per user,
overwritten in place), this is an append-only log: save_conversation_turn
always inserts a new row rather than merging into an existing one.

A save failure here is logged and swallowed rather than raised -- same
reasoning as update_user_memory.py: `response` has already been computed
by this point, and a history-log write failure shouldn't cost the caller
that answer.
"""

import uuid

import psycopg2

from db.upsert import save_conversation_turn

from ..config import MEMORY_ENABLED


def persist_conversation_turn(state):
    if not MEMORY_ENABLED:
        return {}

    user_id = state.get("user_id")
    if not user_id:
        return {}

    try:
        save_conversation_turn(
            {
                "turn_id": str(uuid.uuid4()),
                "user_id": user_id,
                "thread_id": state.get("thread_id"),
                "message": state.get("message"),
                "intent": state.get("intent"),
                "resolved_ticker": state.get("resolved_ticker"),
                "response": state.get("response"),
            }
        )
    except psycopg2.Error as exc:
        print(f"persist_conversation_turn: failed to log turn for user_id={user_id}: {exc}")
    return {}
