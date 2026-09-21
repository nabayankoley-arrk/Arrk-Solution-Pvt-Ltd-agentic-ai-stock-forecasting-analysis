"""Wiring smoke test for the Chat Intent & Routing subgraph's compiled
graph.

Needs everything agents/orchestrator/smoke_test.py needs (Postgres with
the Technical and Fundamental Analysis Agents' tables populated for the
ticker under test, plus "Orchestrator".orchestrator_runs) since a
'stock_market' turn calls straight into that subgraph, plus a Postgres
instance with the "Memory".user_memory and "Memory".conversation_history
tables created (see db/schema.sql).

    python -m agents.chat_intent_routing.smoke_test   # from the backend/ directory
"""

import uuid

from .graph import build_graph

USER_ID = "test-user"

graph = build_graph()


def _thread_config():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def run_stock_query(message, ticker=None):
    request = {"user_id": USER_ID, "message": message}
    if ticker is not None:
        request["ticker"] = ticker
    result = graph.invoke(request, config=_thread_config())

    print(f"--- stock query: {message!r} ---")
    print("intent:", result.get("intent"), "| reason:", result.get("routing_reason"))
    print("response:", result.get("response"))
    print("updated_memory:", result.get("updated_memory"))
    print()


def run_out_of_scope_query(message):
    result = graph.invoke({"user_id": USER_ID, "message": message}, config=_thread_config())

    print(f"--- out-of-scope query: {message!r} ---")
    print("intent:", result.get("intent"), "| reason:", result.get("routing_reason"))
    print("response:", result.get("response"))
    print()


def run_watchlist_fallback():
    """No ticker in the message at all -- relies entirely on the
    watchlist entry the prior run_stock_query call above should have just
    persisted for USER_ID."""
    result = graph.invoke(
        {"user_id": USER_ID, "message": "what's the latest forecast?"}, config=_thread_config()
    )

    print("--- watchlist-fallback query: 'what's the latest forecast?' ---")
    print("intent:", result.get("intent"), "| resolved_ticker:", result.get("resolved_ticker"))
    print("response:", result.get("response"))
    print()


def print_conversation_history():
    """Runs one more turn purely to see load_conversation_history's output
    -- by this point USER_ID should have three prior turns on file (the
    stock query, the watchlist-fallback query, and the out-of-scope
    query), oldest-first."""
    result = graph.invoke(
        {"user_id": USER_ID, "message": "one more, just to load history"}, config=_thread_config()
    )

    print("--- conversation_history loaded for USER_ID (oldest first) ---")
    for turn in result.get("conversation_history") or []:
        print(f"    [{turn['created_at']}] ({turn['intent']}) {turn['message']!r} -> {turn['response']}")
    print()


if __name__ == "__main__":
    # run_stock_query("who is the PM of India?")
    # run_watchlist_fallback()
    run_out_of_scope_query("who is the PM of India?")
    print_conversation_history()
