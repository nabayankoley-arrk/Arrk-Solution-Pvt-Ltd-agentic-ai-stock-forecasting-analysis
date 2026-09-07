"""Wiring smoke test for the User Memory extension's two nodes.

Calls load_user_memory and update_user_memory directly as plain functions
-- there's no compiled graph to invoke() yet, since the base Chat Intent &
Routing subgraph isn't implemented in this repo (see __init__.py). Needs a
Postgres instance with the "Memory".user_memory table created (see
db/schema.sql).

    python -m agents.chat_intent_routing.smoke_test   # from the backend/ directory
"""

from .nodes.load_user_memory import load_user_memory
from .nodes.update_user_memory import update_user_memory

USER_ID = "test-user"


def run():
    memory = load_user_memory({"user_id": USER_ID})
    print("--- load_user_memory (before any writes) ---")
    print(memory)
    print()

    updated = update_user_memory(
        {
            "user_id": USER_ID,
            "user_memory": memory["user_memory"],
            "resolved_ticker": "TCS.NS",
            "memory_update": {"preferences": {"default_horizon": "medium_term"}},
        }
    )
    print("--- update_user_memory (resolved TCS.NS, set default_horizon) ---")
    print(updated)
    print()

    reloaded = load_user_memory({"user_id": USER_ID})
    print("--- load_user_memory (after the write, same user) ---")
    print(reloaded)
    print()


if __name__ == "__main__":
    run()
