"""Chat Intent & Routing subgraph.

Single entry point for an incoming user query: this is the subgraph a
caller invokes directly, never the Orchestrator Subgraph
(agents/orchestrator) -- see graph.py's docstring for the node order.
Stock/market queries are routed on to the Orchestrator Subgraph; every
other intent gets a fixed refusal (nodes/handle_out_of_scope.py) -- this
application answers stock/market questions only, so no other topic is
ever answered. All memory is loaded and
persisted entirely at this layer -- the Orchestrator Subgraph no longer
has any memory fields or nodes of its own. Two distinct stores, both under
the "Memory" schema:

    "Memory".user_memory          -- one row per user (watchlist,
                                      preferences), read/written by
                                      nodes/load_user_memory.py and
                                      nodes/update_user_memory.py
    "Memory".conversation_history -- one row per turn (message + response,
                                      append-only), read/written by
                                      nodes/load_conversation_history.py
                                      and nodes/persist_conversation_turn.py

STATUS: parse_and_route (nodes/parse_and_route.py) is a minimal
placeholder -- no specification for real intent classification has been
shared yet, so it only distinguishes 'stock_market' from 'out_of_scope'
via a resolved ticker or a keyword match (config.STOCK_KEYWORDS). Swap it
for a real classifier without changing any other node's contract.

See graph.py for the compiled StateGraph, or smoke_test.py for a
standalone exercise of a full run through it.
"""
