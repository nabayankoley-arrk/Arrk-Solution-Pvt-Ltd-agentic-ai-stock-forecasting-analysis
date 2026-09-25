"""finalize — reads the turn's outcome off the agent's final message.

Sets the fields main.py returns: `reply` (the agent's answer), `response_type`
('analysis' if an analysis finished this turn, 'error' if the LLM failed,
otherwise 'reply'), and `resolved_ticker`/`response` from the turn's last
analysis, for the ChatResponse and the audit log.
"""

from langchain_core.messages import AIMessage

from .. import config
from ..reply import format_analysis_reply


def message_text(content, strip=True):
    """Message content as plain text: some providers return a list of parts.
    strip=False keeps edge whitespace, which a streamed token needs."""
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    content = content or ""
    return content.strip() if strip else content


def finalize(state):
    last = state["messages"][-1]
    analyses = state.get("analyses") or []
    finished = [
        a for a in analyses if a.get("orchestrator_result") and a["orchestrator_result"].get("final_response")
    ]

    if state.get("action") == "error":
        response_type = "error"
    elif finished:
        response_type = "analysis"
    else:
        response_type = "reply"

    update = {}
    reply = message_text(last.content)
    if not reply:
        # An empty final answer: replace it (same id) so the history stays readable.
        reply = format_analysis_reply(finished[-1]["response"]) if finished else config.UNAVAILABLE_REPLY
        update["messages"] = [AIMessage(reply, id=last.id)]

    latest = analyses[-1] if analyses else {}
    return {
        **update,
        "reply": reply,
        "response_type": response_type,
        "action": response_type,
        "resolved_ticker": latest.get("ticker"),
        "orchestrator_result": latest.get("orchestrator_result"),
        "response": latest.get("response"),
    }
