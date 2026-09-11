"""build_final_response — terminal node.

Final assembly of the reply shown to the user. Reads: conversational_reply.
Writes: final_output, matching the specification's "Final Response"
section: conversational_reply, an indicator of whether the reply resulted
from a full analysis or a single-pillar answer, and updated_context
confirmation for continuity into the next turn.
"""


def build_final_response(state):
    downstream_result = state.get("downstream_result") or {}
    response_type = "single_pillar" if "pillar" in downstream_result else "analysis"

    final_output = {
        "reply": state.get("conversational_reply"),
        "response_type": response_type,
        "session_id": state.get("session_id"),
        "ticker": state.get("resolved_ticker"),
        "updated_context": state.get("updated_context"),
    }
    return {"final_output": final_output}
