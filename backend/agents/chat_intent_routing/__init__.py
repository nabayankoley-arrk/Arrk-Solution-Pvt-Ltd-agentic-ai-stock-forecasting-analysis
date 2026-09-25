"""Chat Intent & Routing subgraph.

The chat layer: a tool-calling agent (see graph.py). The LLM (nodes/agent.py)
reads each message in the context of the conversation, calls analyze_stock
(nodes/tools.py, which runs the Orchestrator Subgraph) when it needs an
analysis, and writes the reply.

Conversation memory is the checkpointer (checkpointer.py), keyed on session_id:
it restores the session's messages and the company under discussion
(current_ticker). Separately, nodes/persist_conversation_turn.py appends every
turn to "Memory".conversation_history as an audit log; nothing reads it back.
"""
