"""Chat Intent & Routing subgraph -- User Memory extension ONLY.

STATUS: this package does not implement the Chat Intent & Routing
subgraph itself -- no specification for that base subgraph (its own
nodes, state, edges, and the conversation_sessions table it reads/writes)
has been shared yet. It implements only the two nodes the "User Memory —
Specification (Chat Intent & Routing Subgraph Extension)" document adds
on top of that base: load_user_memory and update_user_memory, against the
already-created "Memory".user_memory table.

Each node follows the same (state) -> partial-state-update contract every
node in this codebase uses (see e.g. agents/orchestrator/nodes/), so
wiring them into the real base subgraph later is an add_node/add_edge
away, per the extension spec's own edges:

    START -> load_user_memory -> parse_and_route
    ...
    update_session_context -> update_user_memory -> build_final_response

There is no graph.py here (yet) -- a StateGraph needs a base subgraph to
attach these two nodes to, which doesn't exist in this repo. See
nodes/load_user_memory.py and nodes/update_user_memory.py directly, or
smoke_test.py for a standalone (no base graph) exercise of both.

In the meantime, agents/orchestrator/graph.py wires both nodes in
directly (via its own nodes/load_user_memory.py and
nodes/update_user_memory.py thin adapters) so the Orchestrator Subgraph
gets memory-informed ticker resolution and watchlist/preference
persistence without waiting on the base subgraph above. That wiring is
meant to move onto the real Chat Intent & Routing subgraph once it
exists, not stay on the orchestrator permanently.
"""
