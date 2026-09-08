"""Minimal bridge graph for the Chat Intent & Routing package.

This is NOT the real Chat Intent & Routing base subgraph -- there is no
chat-message parsing or intent classification here (see __init__.py: that
base subgraph was never specified/implemented in this repo). It exists so
an API endpoint has something to call that matches the documented shape
"endpoint -> chat_intent_routing -> orchestrator -> technical/fundamental
analysis", using this package's own load_user_memory/update_user_memory
nodes around a direct call into the Orchestrator Subgraph:

    START -> load_user_memory -> invoke_orchestrator -> update_user_memory -> END

Replace this graph's middle wiring once the real base subgraph (with
parse_and_route, conversation_sessions, etc.) is specified and built --
load_user_memory/update_user_memory can move onto that graph unchanged.
"""

from langgraph.graph import END, START, StateGraph

from .nodes.invoke_orchestrator import invoke_orchestrator
from .nodes.load_user_memory import load_user_memory
from .nodes.update_user_memory import update_user_memory
from .state import ChatIntentRoutingState


def build_graph():
    graph = StateGraph(ChatIntentRoutingState)

    graph.add_node("load_user_memory", load_user_memory)
    graph.add_node("invoke_orchestrator", invoke_orchestrator)
    graph.add_node("update_user_memory", update_user_memory)

    graph.add_edge(START, "load_user_memory")
    graph.add_edge("load_user_memory", "invoke_orchestrator")
    graph.add_edge("invoke_orchestrator", "update_user_memory")
    graph.add_edge("update_user_memory", END)

    return graph.compile()
