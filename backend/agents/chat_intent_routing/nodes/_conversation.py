"""Renders the checkpointed conversation for an LLM prompt.

call_llm_chat() takes one system and one user prompt, so earlier turns are
passed as a transcript inside the user prompt. Only the last
config.MAX_HISTORY_TURNS turns are sent, to keep prompts small on free models.
"""

from .. import config


def format_history(messages):
    recent = (messages or [])[-2 * config.MAX_HISTORY_TURNS:]
    if not recent:
        return "(this is the first message)"
    speaker = {"user": "User", "assistant": "Assistant"}
    return "\n".join(f"{speaker.get(m.get('role'), 'User')}: {m.get('content', '')}" for m in recent)
