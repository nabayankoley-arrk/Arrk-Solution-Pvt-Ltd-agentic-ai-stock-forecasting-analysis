"""update_session_context — Response Finalization step.

Persists what was resolved this turn for the next one. Reads:
resolved_ticker, resolved_horizon, resolved_scope, session_id. Writes:
updated_context, and the underlying conversation_sessions row (see
db/schema.sql and db/upsert.save_conversation_session).

Only reached via the format_conversational_reply -> update_session_context
edge (see graph.py), i.e. only after a normal completed analysis turn --
clarification and out-of-scope turns end directly at their own terminal
node instead, same restriction the specification places on this node's
User Memory counterpart (update_user_memory).

Also appends this turn to conversation_messages, for the same reason
build_clarification_response.py / build_out_of_scope_response.py do (see
those modules' docstrings) -- so a completed turn is available to
nodes/load_conversation_context.py's history hydration too, not just
clarification/out-of-scope turns.
"""

import psycopg2

from db.upsert import append_conversation_message, save_conversation_session

from ..config import SESSION_CONTINUITY_ENABLED


def update_session_context(state):
    session_id = state.get("session_id")
    updated_context = {
        "session_id": session_id,
        "last_ticker": state.get("resolved_ticker"),
        "last_horizon": state.get("resolved_horizon"),
        "last_scope": state.get("resolved_scope"),
    }

    if SESSION_CONTINUITY_ENABLED and session_id:
        try:
            save_conversation_session(
                session_id, state.get("resolved_ticker"), state.get("resolved_horizon"), state.get("resolved_scope")
            )
            append_conversation_message(session_id, "user", state.get("raw_message") or "")
            append_conversation_message(session_id, "assistant", state.get("conversational_reply") or "")
        except psycopg2.Error:
            pass

    return {"updated_context": updated_context}
