"""build_out_of_scope_response — terminal node.

Ends the turn with a plain answer or a polite decline. Reads:
downstream_result (if answer_general_question was called this turn) or
out_of_scope_reason. Writes: final_output.

Same conversation_messages logging deviation as
build_clarification_response.py -- see that module's docstring for why.

downstream_result can also hold a failed invoke_orchestrator/
invoke_single_pillar call here (observed in testing: a weaker LLM,
faced with a tool error like a timeout in downstream_result, sometimes
classifies the turn "out_of_scope" with an unrelated/invented reason
instead of retrying or explaining the failure). That tool error is a more
accurate, more useful message than whatever out_of_scope_reason the model
made up, so it takes priority when present.
"""

import psycopg2

from db.upsert import append_conversation_message

from ..config import SESSION_CONTINUITY_ENABLED


def build_out_of_scope_response(state):
    downstream_result = state.get("downstream_result") or {}
    answer = downstream_result.get("answer")
    tool_error = downstream_result.get("error") if not answer else None

    if answer:
        reply = answer
    elif tool_error:
        reply = f"I ran into a problem getting that: {tool_error}"
    else:
        reason = state.get("out_of_scope_reason") or "That's outside what I can help with here."
        reply = f"I can't help with that: {reason}"

    session_id = state.get("session_id")
    if SESSION_CONTINUITY_ENABLED and session_id:
        try:
            append_conversation_message(session_id, "user", state.get("raw_message") or "")
            append_conversation_message(session_id, "assistant", reply)
        except psycopg2.Error:
            pass

    final_output = {
        "reply": reply,
        "response_type": "out_of_scope",
        "session_id": session_id,
        "ticker": state.get("resolved_ticker"),
    }
    return {"conversational_reply": reply, "final_output": final_output}
