"""Chat Intent & Routing Subgraph, plus its User Memory extension.

Implements both specification documents this package is built from:
  - "Chat Intent & Routing Subgraph — Specification" (parse_and_route as
    the sole decision-maker; execute_tool_call, build_clarification_response,
    build_out_of_scope_response, format_conversational_reply,
    update_session_context, build_final_response as the deterministic
    steps around it; see graph.py).
  - "User Memory — Specification (Chat Intent & Routing Subgraph
    Extension)" (load_user_memory / update_user_memory; see config.py's
    MAX_WATCHLIST_SIZE/MEMORY_ENABLED and nodes/load_user_memory.py,
    nodes/update_user_memory.py).

See graph.py's own module docstring for the one deviation from both
documents (load_conversation_context) and why it exists, and
smoke_test.py for a runnable multi-turn walkthrough (analysis,
clarification, out-of-scope, and session continuity across separate
graph.invoke() calls).

agents/orchestrator/graph.py also wires load_user_memory/update_user_memory
in directly (via its own nodes/load_user_memory.py, nodes/update_user_memory.py
thin adapters over this package's shared implementation), so the
Orchestrator Subgraph can still be exercised standalone with
memory-informed ticker resolution -- not because the Orchestrator is
supposed to own this behavior long-term.
"""
