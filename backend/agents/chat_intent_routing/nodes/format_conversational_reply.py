"""format_conversational_reply — Response Finalization step.

Turns the structured downstream analysis result (from invoke_orchestrator
or invoke_single_pillar) into a conversational message. Reads:
downstream_result. Writes: conversational_reply. Surfaces the narrative
and key highlights rather than raw structured output, per the
specification -- delegated to ..llm_client.format_conversational_reply,
which falls back to a deterministic summary if the LLM can't be reached
(a formatting failure shouldn't fail an otherwise-successful analysis).
"""

from ..llm_client import format_conversational_reply as _format_conversational_reply_llm


def format_conversational_reply(state):
    downstream_result = state.get("downstream_result") or {}

    if downstream_result.get("error"):
        reply = f"I ran into a problem getting that analysis: {downstream_result['error']}"
    else:
        # invoke_single_pillar wraps its pillar's output under "result";
        # invoke_orchestrator returns the analysis dict directly.
        payload = downstream_result.get("result") if "result" in downstream_result else downstream_result
        reply = _format_conversational_reply_llm(payload)

    return {"conversational_reply": reply}
