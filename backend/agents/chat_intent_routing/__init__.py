"""Chat Intent & Routing subgraph.

The chat layer (see graph.py for the node order). An LLM (nodes/interpret.py)
reads each message in the context of the conversation and decides whether to
answer directly, refuse, or run the Orchestrator Subgraph; after an analysis a
second LLM call (nodes/respond.py) writes the answer.

Conversation memory is the checkpointer (checkpointer.py), keyed on session_id:
it restores the session's messages and the company under discussion
(current_ticker). Separately, nodes/persist_conversation_turn.py appends every
turn to "Memory".conversation_history as an audit log; nothing reads it back.
"""
