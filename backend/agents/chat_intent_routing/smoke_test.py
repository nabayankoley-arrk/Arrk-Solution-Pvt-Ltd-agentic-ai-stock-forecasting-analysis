"""End-to-end smoke test for the Chat Intent & Routing subgraph: one
conversation, several turns, so each turn can lean on the ones before it.

Needs a live LLM (LLM_PROVIDER + key in backend/.env) and everything
agents/orchestrator/smoke_test.py needs for the analysis turn, plus the
"Memory" tables (see db/schema.sql). Uses an in-process MemorySaver, so it
leaves no checkpoints behind.

    python -m agents.chat_intent_routing.smoke_test   # from the backend/ directory
"""

import uuid

from langgraph.checkpoint.memory import MemorySaver

from .graph import build_graph, turn_input

USER_ID = "test-user"
CONVERSATION = (
    "hi, what can you do?",
    "how is TCS looking?",
    "what was its support level again?",
    "and Infosys?",
    "who is the PM of India?",
)

graph = build_graph(checkpointer=MemorySaver())


if __name__ == "__main__":
    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}
    for message in CONVERSATION:
        result = graph.invoke(turn_input(user_id=USER_ID, message=message, thread_id=session_id), config=config)
        print(f"--- {message!r} ---")
        print("action:", result.get("action"), "| ticker:", result.get("resolved_ticker"))
        print("reply:", result.get("reply"))
        print()
