"""Wiring smoke test for the Chat Intent & Routing Subgraph's state graph.

Unlike agents/orchestrator/smoke_test.py, this graph has no checkpointer/
thread_id -- continuity across "turns" here is entirely via Postgres
(conversation_sessions/conversation_messages, "Memory".user_memory), the
same way two genuinely separate HTTP requests to POST /api/chat would see
continuity (see main.py). Each run_turn() call below is therefore its own
independent graph.invoke(), exactly like a fresh API request would be.

parse_and_route has no rule-based fallback for entity extraction/intent
classification (see llm_client.py's module docstring) -- without a
reachable LLM (OPENROUTER_API_KEY set, or LLM_PROVIDER=ollama with
`ollama serve` running), every turn below will fall back to a generic
clarification question instead of actually resolving a ticker or
finalizing an analysis. That's still enough to exercise the graph's
wiring and session/user-memory persistence end to end; wire up a real LLM
Agent to see the tool_call/finalize/out_of_scope paths.

    python -m agents.chat_intent_routing.smoke_test   # from the backend/ directory
"""

import uuid

from .graph import build_graph

graph = build_graph()


def run_turn(raw_message, session_id=None, user_id=None):
    request = {"raw_message": raw_message, "session_id": session_id or str(uuid.uuid4())}
    if user_id is not None:
        request["user_id"] = user_id

    result = graph.invoke(request)
    final_output = result.get("final_output")

    print(f"--- turn: {raw_message!r} (session_id={request['session_id']}) ---")
    print(f"    routing_decision: {result.get('routing_decision')}")
    print(f"    resolved_ticker:  {result.get('resolved_ticker')}")
    print(f"    reply:            {final_output.get('reply') if final_output else None}")
    print(f"    conversation_history hydrated for this turn: {result.get('conversation_history')}")
    print()
    return final_output["session_id"]


def run_multi_turn_session():
    """Two turns in the *same* session, each its own graph.invoke() call
    (simulating two separate HTTP requests) -- demonstrates that
    conversation_history on turn 2 is hydrated from conversation_messages
    using only session_id, without the caller resending turn 1's message.
    """
    session_id = run_turn("What do you think about INFY.NS?", user_id="test-user")
    run_turn("What about its fundamentals?", session_id=session_id, user_id="test-user")


def run_new_session_each_time():
    """No session_id passed -- a brand-new session (and UUID) is minted
    for every call, so no conversation_history is hydrated.
    """
    run_turn("Tell me about the weather today")


if __name__ == "__main__":
    run_multi_turn_session()
    run_new_session_each_time()
