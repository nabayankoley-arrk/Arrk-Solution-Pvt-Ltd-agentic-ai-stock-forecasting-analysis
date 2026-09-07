"""Assembles the Orchestrator Subgraph's state graph.

    load_user_memory -> validate_input
       |- invalid -> build_error_response -> persist_run -> END
       `- valid   -> fetch_technical_analysis    -\\
                     fetch_fundamental_analysis   -+-> reconcile_and_decide
                     fetch_sentiment_analysis     -/        |
                                                             |- call_tool -----------------------> execute_tool_call -> reconcile_and_decide
                                                             |- finalize, requires_review=False --> build_final_response -> update_user_memory -> persist_run -> END
                                                             `- finalize, requires_review=True ---> request_human_review
                                                                                                        |- approve/edit -> build_final_response -> update_user_memory -> persist_run -> END
                                                                                                        `- rerun --------> execute_tool_call -> reconcile_and_decide

The three baseline fetch nodes execute independently and are joined by
LangGraph's own superstep synchronization before reconcile_and_decide (the
one LLM-driven node) runs -- the same fan-out/fan-in pattern already used
inside the Technical and Fundamental Analysis Agents' own graphs for their
parallel signal nodes (see agents/technical_analysis/graph.py,
agents/fundamental_analysis/graph.py). This is exactly the lead's
Orchestrator Subgraph specification -- no ml_forecast pillar. The trained
ML price-forecast model (ml/predict.py) is kept as a standalone module
under backend/ml/, decoupled from the orchestrator so it can be wired back
in later without reworking this graph.

load_user_memory and update_user_memory are thin adapters (see
nodes/load_user_memory.py, nodes/update_user_memory.py) over the User
Memory extension's shared implementation in agents/chat_intent_routing --
wired directly into this graph since the Chat Intent & Routing base
subgraph they were originally specified against isn't implemented in this
repo yet. Both no-op gracefully (empty memory / no persistence) when the
caller omits user_id, so existing callers that don't pass it see no
behavior change at all.

An optional forecast_days input (see state.py's note on that field) rides
alongside ticker/horizon without adding a graph node: build_final_response
calls forecast_price_range.py directly when it's supplied, attaching the
result to final_response["price_forecast"]. Omitted, it costs nothing.

Human review is a real pause, not a callback: request_human_review calls
langgraph.types.interrupt(), so build_graph() requires a checkpointer -- a
MemorySaver by default here, adequate for local smoke-testing; swap for a
persistent one (e.g. a Postgres-backed saver) for anything that must
survive a process restart while a run is paused. Callers resume a paused
run with:

    graph.invoke(Command(resume={...}), config={"configurable": {"thread_id": thread_id}})

using the same thread_id the original graph.invoke() call used.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes.build_error_response import build_error_response
from .nodes.build_final_response import build_final_response
from .nodes.execute_tool_call import execute_tool_call
from .nodes.fetch_fundamental_analysis import fetch_fundamental_analysis
from .nodes.fetch_sentiment_analysis import fetch_sentiment_analysis
from .nodes.fetch_technical_analysis import fetch_technical_analysis
from .nodes.load_user_memory import load_user_memory
from .nodes.persist_run import persist_run
from .nodes.reconcile_and_decide import reconcile_and_decide
from .nodes.request_human_review import request_human_review
from .nodes.update_user_memory import update_user_memory
from .nodes.validate_input import validate_input
from .state import OrchestratorState

BASELINE_ANALYSIS_NODES = [
    "fetch_technical_analysis",
    "fetch_fundamental_analysis",
    "fetch_sentiment_analysis",
]


def route_after_validate(state: OrchestratorState):
    return BASELINE_ANALYSIS_NODES if state.get("is_valid") else ["build_error_response"]


def route_after_reconcile(state: OrchestratorState) -> str:
    if state.get("decision") == "call_tool":
        return "execute_tool_call"
    return "request_human_review" if state.get("requires_review") else "build_final_response"


def route_after_review(state: OrchestratorState) -> str:
    return "execute_tool_call" if state.get("reviewer_decision") == "rerun" else "build_final_response"


def build_graph(checkpointer=None):
    graph = StateGraph(OrchestratorState)

    graph.add_node("load_user_memory", load_user_memory)
    graph.add_node("validate_input", validate_input)
    graph.add_node("build_error_response", build_error_response)
    graph.add_node("fetch_technical_analysis", fetch_technical_analysis)
    graph.add_node("fetch_fundamental_analysis", fetch_fundamental_analysis)
    graph.add_node("fetch_sentiment_analysis", fetch_sentiment_analysis)
    graph.add_node("reconcile_and_decide", reconcile_and_decide)
    graph.add_node("execute_tool_call", execute_tool_call)
    graph.add_node("request_human_review", request_human_review)
    graph.add_node("build_final_response", build_final_response)
    graph.add_node("update_user_memory", update_user_memory)
    graph.add_node("persist_run", persist_run)

    graph.add_edge(START, "load_user_memory")
    graph.add_edge("load_user_memory", "validate_input")
    graph.add_conditional_edges(
        "validate_input", route_after_validate, BASELINE_ANALYSIS_NODES + ["build_error_response"]
    )

    for node in BASELINE_ANALYSIS_NODES:
        graph.add_edge(node, "reconcile_and_decide")

    graph.add_conditional_edges(
        "reconcile_and_decide",
        route_after_reconcile,
        ["execute_tool_call", "request_human_review", "build_final_response"],
    )
    graph.add_edge("execute_tool_call", "reconcile_and_decide")
    graph.add_conditional_edges(
        "request_human_review", route_after_review, ["execute_tool_call", "build_final_response"]
    )

    graph.add_edge("build_final_response", "update_user_memory")
    graph.add_edge("update_user_memory", "persist_run")
    graph.add_edge("build_error_response", "persist_run")
    graph.add_edge("persist_run", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
