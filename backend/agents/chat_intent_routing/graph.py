"""Assembles the Chat Intent & Routing subgraph.

    START -> interpret
               |- action='analyze' -> route_to_orchestrator -> respond -\
               `- otherwise (reply / out_of_scope / error) ---------------+-> persist_conversation_turn -> END

interpret (LLM) reads the message in the context of the conversation and
decides; respond (LLM) writes the answer from the Orchestrator's result.
Any other action already carries interpret's reply.

Conversation memory is the checkpointer (see checkpointer.py): invoke with
config={"configurable": {"thread_id": session_id}} and `messages` and
`current_ticker` carry over between turns. Every other field is per-turn, so
callers start each turn from turn_input(), which resets them -- otherwise a
checkpointed value from the previous turn (a response, a reply) would leak
into this one.
"""

from langgraph.graph import END, START, StateGraph

from .nodes.interpret import interpret
from .nodes.persist_conversation_turn import persist_conversation_turn
from .nodes.respond import respond
from .nodes.route_to_orchestrator import route_to_orchestrator
from .state import ChatIntentRoutingState

_PER_TURN_FIELDS = (
    "ticker", "horizon", "forecast_days", "thread_id",
    "action", "resolved_ticker", "routing_reason", "orchestrator_result", "response", "reply",
)


def turn_input(**fields):
    """Input for one turn: the given fields, every other per-turn field reset."""
    return {**dict.fromkeys(_PER_TURN_FIELDS), **fields}


def route_after_interpret(state: ChatIntentRoutingState) -> str:
    return "route_to_orchestrator" if state.get("action") == "analyze" else "persist_conversation_turn"


def build_graph(checkpointer=None):
    graph = StateGraph(ChatIntentRoutingState)

    graph.add_node("interpret", interpret)
    graph.add_node("route_to_orchestrator", route_to_orchestrator)
    graph.add_node("respond", respond)
    graph.add_node("persist_conversation_turn", persist_conversation_turn)

    graph.add_edge(START, "interpret")
    graph.add_conditional_edges(
        "interpret", route_after_interpret, ["route_to_orchestrator", "persist_conversation_turn"]
    )
    graph.add_edge("route_to_orchestrator", "respond")
    graph.add_edge("respond", "persist_conversation_turn")
    graph.add_edge("persist_conversation_turn", END)

    return graph.compile(checkpointer=checkpointer)
