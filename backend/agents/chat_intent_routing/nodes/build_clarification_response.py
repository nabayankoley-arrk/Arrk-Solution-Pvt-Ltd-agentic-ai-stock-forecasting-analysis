"""build_clarification_response — terminal node.

Ends the turn with a question back to the user rather than guessing.
Reads: clarification_question. Writes: final_output = the clarification
question as the chat reply.

clarification_question can be None here even though this node was
reached: graph.py's loop guard force-routes here once requery_count hits
MAX_PARSE_LOOPS regardless of parse_and_route's last decision, which may
have been "tool_call" (with clarification_question never set) right up
until the guard tripped. Falls back to a generic message in that case so
this always produces a real reply string, per specification -- and per
main.py's ChatResponse contract, which requires reply to be a string.

Also appends this turn to conversation_messages -- not in the
specification's own Reads/Writes for this node, but needed so the next
request against the same session_id (see
nodes/load_conversation_context.py) still has this exchange in its
hydrated conversation_history; otherwise a clarification round-trip would
look like amnesia to the user on the very next message. This does NOT
call update_session_context / persist resolved_ticker-style session
state -- per the specification, that only happens after a normal
completed response, same restriction the User Memory extension places on
update_user_memory.
"""

import psycopg2

from db.upsert import append_conversation_message

from ..config import SESSION_CONTINUITY_ENABLED


_LOOP_GUARD_FALLBACK = (
    "I'm still not able to pin this down -- could you tell me the exact ticker symbol and whether you want "
    "the technical, fundamental, sentiment, or overall analysis?"
)


def build_clarification_response(state):
    clarification_question = state.get("clarification_question") or _LOOP_GUARD_FALLBACK

    session_id = state.get("session_id")
    if SESSION_CONTINUITY_ENABLED and session_id:
        try:
            append_conversation_message(session_id, "user", state.get("raw_message") or "")
            append_conversation_message(session_id, "assistant", clarification_question or "")
        except psycopg2.Error:
            pass

    final_output = {
        "reply": clarification_question,
        "response_type": "clarification",
        "session_id": session_id,
        "ticker": state.get("resolved_ticker"),
    }
    return {"conversational_reply": clarification_question, "final_output": final_output}
