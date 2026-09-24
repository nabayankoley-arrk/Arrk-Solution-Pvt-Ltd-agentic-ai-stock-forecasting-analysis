"""respond — turns the Orchestrator's result into the chat reply.

For a finished analysis, the LLM writes a conversational answer to what the
user actually asked, from a compact digest of the result (reply.analysis_digest,
which already strips internal/operational detail). If that call fails, the
fixed template (reply.format_analysis_reply) is used instead, so a finished
analysis is never lost to an LLM hiccup.

An Orchestrator error becomes an error reply without an LLM call. Skipped for
a caller-supplied ticker (POST /api/stock-analysis returns the raw result).
"""

import json

from agents.orchestrator.llm_client import call_llm_chat, extract_json_object

from .. import config
from ..reply import analysis_digest, format_analysis_reply, is_internal_detail, outcome
from ._conversation import format_history

_SYSTEM_PROMPT = """You are the chat assistant of a stock-analysis app. You are given the result \
of an analysis the app just ran, the conversation so far, and the user's latest message.

Answer the latest message using ONLY the figures and signals in the analysis result -- never \
invent numbers. Lead with what the user asked about, then the overall signal. Mention clearly \
when a pillar (technical, fundamental, sentiment) was unavailable. Keep it to a short paragraph \
or a few bullet points. This is information, not personalised investment advice.

Respond with ONLY one JSON object: {"reply": "<your answer>"}"""


def _write_reply(state, response):
    user_prompt = (
        f"Analysis result:\n{json.dumps(analysis_digest(response), default=str)}\n\n"
        f"Conversation so far:\n{format_history((state.get('messages') or [])[:-1])}\n\n"
        f"Latest message: {state.get('message') or ''}"
    )
    reply = (extract_json_object(call_llm_chat(_SYSTEM_PROMPT, user_prompt)).get("reply") or "").strip()
    if not reply:
        raise ValueError("empty reply")
    return reply


def respond(state):
    if state.get("ticker"):
        return {}

    response = state.get("response") or {}
    result_outcome = outcome(state)
    if result_outcome == "analysis":
        try:
            reply = _write_reply(state, response)
        except Exception as exc:
            print(f"[chat] respond failed, using template: {type(exc).__name__}: {exc}", flush=True)
            reply = format_analysis_reply(response)
    else:
        if result_outcome == "failed":
            print(f"[chat] orchestrator failed: {response.get('reason')}", flush=True)
        reason = response.get("reason") if result_outcome == "invalid" else None
        reply = reason if reason and not is_internal_detail(reason) else config.ERROR_REPLY

    return {"reply": reply, "messages": [{"role": "assistant", "content": reply}]}
