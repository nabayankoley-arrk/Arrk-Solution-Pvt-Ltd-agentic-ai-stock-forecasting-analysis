"""Assembles the Chat Intent & Routing subgraph's state graph.

    START -\\
            +-> load_user_memory           -\\
            `-> load_conversation_history   -+-> parse_and_route
                                                 |- intent='stock_market' -> route_to_orchestrator -\\
                                                 `- intent='out_of_scope' -> handle_out_of_scope     +-> update_user_memory        -\\
                                                                                                       `-> persist_conversation_turn -+-> END

This is the single entry point for an incoming user query -- stock/market
questions are routed to the Orchestrator Subgraph (route_to_orchestrator);
everything else gets handle_out_of_scope's fixed refusal, since this
application answers stock/market questions only (see that node's
docstring). The Orchestrator
Subgraph itself no longer touches user_id/user_memory: this subgraph loads
memory before routing (so parse_and_route can resolve a ticker from the
caller's watchlist) and persists it after, regardless of which branch ran
-- update_user_memory no-ops on its own when there's no user_id or no
resolved_ticker, so running it unconditionally costs nothing on the
out_of_scope path.

load_user_memory and load_conversation_history run in parallel (both only
read `user_id`, joined by LangGraph's own superstep synchronization before
parse_and_route runs -- the same fan-out/fan-in pattern the Orchestrator
Subgraph's three baseline fetch nodes use) and write to different state
keys (user_memory vs. conversation_history), so no merge reducer is
needed. update_user_memory and persist_conversation_turn are fanned out
the same way at the end -- neither reads the other's output either.

update_user_memory and persist_conversation_turn both run even when
route_to_orchestrator's response was the Orchestrator Subgraph's own
error_response (e.g. bad horizon) -- a deliberate simplification for this
minimal version: update_user_memory only ever persists a watchlist entry
when resolved_ticker is set, and persist_conversation_turn logs every turn
regardless of outcome on purpose (an out_of_scope or errored turn is still
useful context for a later one).

load_user_memory, update_user_memory, load_conversation_history, and
persist_conversation_turn are all used directly here -- each already reads/
writes exactly the state keys this graph's own ChatIntentRoutingState
defines, so unlike the Orchestrator Subgraph's old wiring, no adapter layer
is needed.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes.handle_out_of_scope import handle_out_of_scope
from .nodes.load_conversation_history import load_conversation_history
from .nodes.load_user_memory import load_user_memory
from .nodes.parse_and_route import parse_and_route
from .nodes.persist_conversation_turn import persist_conversation_turn
from .nodes.route_to_orchestrator import route_to_orchestrator
from .nodes.update_user_memory import update_user_memory
from .state import ChatIntentRoutingState


def route_after_parse(state: ChatIntentRoutingState) -> str:
    return "route_to_orchestrator" if state.get("intent") == "stock_market" else "handle_out_of_scope"


def build_graph(checkpointer=None):
    graph = StateGraph(ChatIntentRoutingState)

    graph.add_node("load_user_memory", load_user_memory)
    graph.add_node("load_conversation_history", load_conversation_history)
    graph.add_node("parse_and_route", parse_and_route)
    graph.add_node("route_to_orchestrator", route_to_orchestrator)
    graph.add_node("handle_out_of_scope", handle_out_of_scope)
    graph.add_node("update_user_memory", update_user_memory)
    graph.add_node("persist_conversation_turn", persist_conversation_turn)

    graph.add_edge(START, "load_user_memory")
    graph.add_edge(START, "load_conversation_history")
    graph.add_edge("load_user_memory", "parse_and_route")
    graph.add_edge("load_conversation_history", "parse_and_route")

    graph.add_conditional_edges(
        "parse_and_route", route_after_parse, ["route_to_orchestrator", "handle_out_of_scope"]
    )

    for node in ("route_to_orchestrator", "handle_out_of_scope"):
        graph.add_edge(node, "update_user_memory")
        graph.add_edge(node, "persist_conversation_turn")

    graph.add_edge("update_user_memory", END)
    graph.add_edge("persist_conversation_turn", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
