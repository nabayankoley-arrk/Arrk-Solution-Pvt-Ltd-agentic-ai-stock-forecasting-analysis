"""Assembles the Orchestrator Subgraph.

    START -> validate_input
       |- invalid -> build_error_response -> persist_run -> END
       `- valid   -> plan_analysis -> (the planned pillars, in parallel)
                        fetch_technical_analysis    -\\
                        fetch_fundamental_analysis   -+-> reconcile_and_decide
                        fetch_sentiment_analysis     -/        |
                                                                |- call_tool -> execute_tool_call -> reconcile_and_decide
                                                                `- finalize  -> build_final_response -> persist_run -> END

plan_analysis picks the pillars and their weights for the horizon
(config.HORIZON_PLAN): short term skips fundamentals. reconcile_and_decide
(the LLM step) may rerun one planned pillar, then finalizes with a verdict --
overall direction, confidence, key drivers and conflicts (nodes/_verdict.py).
Pillar disagreement is reported in the verdict, not paused on, so the graph
needs no checkpointer.

With forecast_days, build_final_response also attaches a price range anchored
on the technical pillar's volatility (forecast_price_range.py).
"""

from langgraph.graph import END, START, StateGraph

from .nodes.build_error_response import build_error_response
from .nodes.build_final_response import build_final_response
from .nodes.execute_tool_call import execute_tool_call
from .nodes.fetch_fundamental_analysis import fetch_fundamental_analysis
from .nodes.fetch_sentiment_analysis import fetch_sentiment_analysis
from .nodes.fetch_technical_analysis import fetch_technical_analysis
from .nodes.persist_run import persist_run
from .nodes.plan_analysis import plan_analysis
from .nodes.reconcile_and_decide import reconcile_and_decide
from .nodes.validate_input import validate_input
from .state import OrchestratorState

FETCH_NODES = {
    "technical": "fetch_technical_analysis",
    "fundamental": "fetch_fundamental_analysis",
    "sentiment": "fetch_sentiment_analysis",
}


def route_after_validate(state: OrchestratorState) -> str:
    return "plan_analysis" if state.get("is_valid") else "build_error_response"


def route_after_plan(state: OrchestratorState) -> list:
    return [FETCH_NODES[p] for p in state["planned_pillars"]]


def route_after_reconcile(state: OrchestratorState) -> str:
    return "execute_tool_call" if state.get("decision") == "call_tool" else "build_final_response"


def build_graph(checkpointer=None):
    graph = StateGraph(OrchestratorState)

    graph.add_node("validate_input", validate_input)
    graph.add_node("build_error_response", build_error_response)
    graph.add_node("plan_analysis", plan_analysis)
    for node, fn in (
        ("fetch_technical_analysis", fetch_technical_analysis),
        ("fetch_fundamental_analysis", fetch_fundamental_analysis),
        ("fetch_sentiment_analysis", fetch_sentiment_analysis),
    ):
        graph.add_node(node, fn)
    graph.add_node("reconcile_and_decide", reconcile_and_decide)
    graph.add_node("execute_tool_call", execute_tool_call)
    graph.add_node("build_final_response", build_final_response)
    graph.add_node("persist_run", persist_run)

    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges("validate_input", route_after_validate, ["plan_analysis", "build_error_response"])
    graph.add_conditional_edges("plan_analysis", route_after_plan, list(FETCH_NODES.values()))
    for node in FETCH_NODES.values():
        graph.add_edge(node, "reconcile_and_decide")

    graph.add_conditional_edges(
        "reconcile_and_decide", route_after_reconcile, ["execute_tool_call", "build_final_response"]
    )
    graph.add_edge("execute_tool_call", "reconcile_and_decide")
    graph.add_edge("build_final_response", "persist_run")
    graph.add_edge("build_error_response", "persist_run")
    graph.add_edge("persist_run", END)

    return graph.compile(checkpointer=checkpointer)
