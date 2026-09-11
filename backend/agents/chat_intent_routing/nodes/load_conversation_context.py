"""load_conversation_context — session-continuity retrieval node.

NOT a node either specification document names. Both documents treat
conversation_history as caller-supplied Input and conversation_sessions/
conversation_messages purely as something update_session_context *writes*
("Optional, for audit/debugging conversation flow rather than resolution
logic" for conversation_messages). Taken completely literally, that means
a client must accumulate and resend the entire conversation_history array
on every request -- workable, but it defeats the point of returning a
session_id at all for a plain HTTP client that just wants to say
"remember what we were talking about" by session_id alone.

This node makes session_id actually carry that continuity for a stateless
HTTP endpoint, the same way the User Memory extension's load_user_memory
makes user_id carry continuity across sessions:
  - Loads conversation_sessions' last_ticker/last_horizon/last_scope into
    session_context, so parse_and_route can resolve a follow-up like
    "how's it looking today?" from the last resolved ticker in *this*
    session -- the session-scoped counterpart to the User Memory
    extension's watchlist-based fallback.
  - Hydrates conversation_history from conversation_messages when the
    caller didn't supply one, so a client only needs to send session_id
    + the new raw_message on turn 2+ instead of replaying the whole
    conversation. A caller-supplied conversation_history always wins.

Degrades to empty context (not an error) on a missing session_id, a
disabled SESSION_CONTINUITY_ENABLED, or a DB hiccup -- same graceful-
degradation convention as load_user_memory.py.
"""

import psycopg2

from db.connection import get_connection

from ..config import MAX_HISTORY_MESSAGES, SESSION_CONTINUITY_ENABLED

_EMPTY_CONTEXT = {"last_ticker": None, "last_horizon": None, "last_scope": None}


def load_conversation_context(state):
    session_id = state.get("session_id")
    if not SESSION_CONTINUITY_ENABLED or not session_id:
        return {"session_context": dict(_EMPTY_CONTEXT), "conversation_history": state.get("conversation_history") or []}

    try:
        conn = get_connection()
    except psycopg2.OperationalError:
        return {"session_context": dict(_EMPTY_CONTEXT), "conversation_history": state.get("conversation_history") or []}

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_ticker, last_horizon, last_scope FROM conversation_sessions WHERE session_id = %s",
                (session_id,),
            )
            session_row = cur.fetchone()

            conversation_history = state.get("conversation_history")
            if not conversation_history:
                cur.execute(
                    """
                    SELECT role, content FROM conversation_messages
                    WHERE session_id = %s
                    ORDER BY turn_index DESC
                    LIMIT %s
                    """,
                    (session_id, MAX_HISTORY_MESSAGES),
                )
                rows = list(reversed(cur.fetchall()))
                conversation_history = [{"role": role, "content": content} for role, content in rows]
    except psycopg2.Error:
        return {"session_context": dict(_EMPTY_CONTEXT), "conversation_history": state.get("conversation_history") or []}
    finally:
        conn.close()

    if session_row is None:
        session_context = dict(_EMPTY_CONTEXT)
    else:
        last_ticker, last_horizon, last_scope = session_row
        session_context = {"last_ticker": last_ticker, "last_horizon": last_horizon, "last_scope": last_scope}

    return {"session_context": session_context, "conversation_history": conversation_history}
