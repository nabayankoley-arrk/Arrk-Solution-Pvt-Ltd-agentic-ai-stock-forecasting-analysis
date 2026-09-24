"""persist_conversation_turn — audit-log node.

Appends this turn (the caller's message, the action taken and the reply) to
"Memory".conversation_history. Runs on every turn, whatever the action. This is
an audit trail only: the conversation itself is restored from the checkpointer.

No-ops without a user_id (nothing to key the row on) or when
config.MEMORY_ENABLED is False. A save failure is logged and swallowed: the
reply is already computed, and a log write shouldn't cost the caller the answer.
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
                "intent": state.get("action"),
                "resolved_ticker": state.get("resolved_ticker"),
                "response": {"reply": state.get("reply"), "analysis": state.get("response")},
            }
        )
    except psycopg2.Error as exc:
        print(f"persist_conversation_turn: failed to log turn for user_id={user_id}: {exc}")
    return {}
