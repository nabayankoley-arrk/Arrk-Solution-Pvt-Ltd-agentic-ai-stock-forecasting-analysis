"""Assembles the Chat Intent & Routing subgraph: a tool-calling chat agent.

    START -> agent <-> tools            (loops while the agent calls tools)
               `-> finalize -\\
    START -> direct_analysis --+-> persist_conversation_turn -> END

agent (LLM) reads the conversation, calls analyze_stock when it needs an
analysis, and answers once it has what it needs. A caller-supplied ticker
(POST /api/stock-analysis) takes the direct_analysis path instead: no LLM.

Conversation memory is the checkpointer (see checkpointer.py): invoke with
config={"configurable": {"thread_id": session_id}} and `messages` and
`current_ticker` carry over between turns. Every other field is per-turn, so
callers start each turn from turn_input(), which resets them -- otherwise a
checkpointed value from the previous turn (a reply, an analysis) would leak
into this one.
"""

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from .nodes.agent import agent
from .nodes.direct_analysis import direct_analysis
from .nodes.finalize import finalize
from .nodes.persist_conversation_turn import persist_conversation_turn
from .nodes.tools import tools
from .state import ChatIntentRoutingState

_PER_TURN_FIELDS = (
    "ticker", "horizon", "forecast_days", "thread_id", "message",
    "tool_rounds", "analyses",
    "action", "reply", "response_type", "resolved_ticker", "orchestrator_result", "response",
)


def turn_input(**fields):
    """Input for one turn: the given fields, every other per-turn field reset.
    A chat message is also appended to the conversation."""
    turn = {**dict.fromkeys(_PER_TURN_FIELDS), **fields}
    if fields.get("message") and not fields.get("ticker"):
        turn["messages"] = [HumanMessage(fields["message"])]
    return turn


def route_start(state: ChatIntentRoutingState) -> str:
    return "direct_analysis" if state.get("ticker") else "agent"


def route_after_agent(state: ChatIntentRoutingState) -> str:
    return "tools" if getattr(state["messages"][-1], "tool_calls", None) else "finalize"


def build_graph(checkpointer=None):
    graph = StateGraph(ChatIntentRoutingState)

    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("finalize", finalize)
    graph.add_node("direct_analysis", direct_analysis)
    graph.add_node("persist_conversation_turn", persist_conversation_turn)

    graph.add_conditional_edges(START, route_start, ["agent", "direct_analysis"])
    graph.add_conditional_edges("agent", route_after_agent, ["tools", "finalize"])
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", "persist_conversation_turn")
    graph.add_edge("direct_analysis", "persist_conversation_turn")
    graph.add_edge("persist_conversation_turn", END)

    return graph.compile(checkpointer=checkpointer)
