"""Assembles the Fundamental Analysis Agent's state graph.

Control flow mirrors docs/fundamental-analysis-design.md Section 3.3:

    validate_input
       |- invalid  -> build_error_response -> END
       `- valid    -> fetch_fundamentals_data
                         |- failed  -> build_error_response -> END
                         `- success -> check_data_sufficiency
                                          |- insufficient -> build_error_response -> END
                                          `- sufficient   -> fan out:
                                                 compute_relative_valuation
                                                 compute_growth
                                                 compute_financial_health
                                                 compute_analyst_consensus
                                             (fan-in) -> aggregate_composite_signal
                                                            -> build_success_response -> END
"""

from langgraph.graph import END, START, StateGraph

from .nodes.aggregate_composite_signal import aggregate_composite_signal
from .nodes.build_error_response import build_error_response
from .nodes.build_success_response import build_success_response
from .nodes.check_data_sufficiency import check_data_sufficiency
from .nodes.compute_analyst_consensus import compute_analyst_consensus
from .nodes.compute_financial_health import compute_financial_health
from .nodes.compute_growth import compute_growth
from .nodes.compute_relative_valuation import compute_relative_valuation
from .nodes.fetch_fundamentals_data import fetch_fundamentals_data
from .nodes.persist_results import persist_results
from .nodes.validate_input import validate_input
from .state import FundamentalAnalysisState

SIGNAL_NODES = [
    "compute_relative_valuation",
    "compute_growth",
    "compute_financial_health",
    "compute_analyst_consensus",
]


def route_after_validate(state: FundamentalAnalysisState) -> str:
    return "fetch_fundamentals_data" if state.get("is_valid") else "build_error_response"


def route_after_fetch(state: FundamentalAnalysisState) -> str:
    return "build_error_response" if state.get("fetch_failed") else "check_data_sufficiency"


def route_after_sufficiency(state: FundamentalAnalysisState):
    if state.get("data_tier") == "insufficient":
        return ["build_error_response"]
    return SIGNAL_NODES


def build_graph():
    graph = StateGraph(FundamentalAnalysisState)

    graph.add_node("validate_input", validate_input)
    graph.add_node("fetch_fundamentals_data", fetch_fundamentals_data)
    graph.add_node("check_data_sufficiency", check_data_sufficiency)
    graph.add_node("build_error_response", build_error_response)
    graph.add_node("compute_relative_valuation", compute_relative_valuation)
    graph.add_node("compute_growth", compute_growth)
    graph.add_node("compute_financial_health", compute_financial_health)
    graph.add_node("compute_analyst_consensus", compute_analyst_consensus)
    graph.add_node("aggregate_composite_signal", aggregate_composite_signal)
    graph.add_node("build_success_response", build_success_response)
    graph.add_node("persist_results", persist_results)

    graph.add_edge(START, "validate_input")

    graph.add_conditional_edges(
        "validate_input", route_after_validate, ["fetch_fundamentals_data", "build_error_response"]
    )
    graph.add_conditional_edges(
        "fetch_fundamentals_data", route_after_fetch, ["check_data_sufficiency", "build_error_response"]
    )
    graph.add_conditional_edges(
        "check_data_sufficiency", route_after_sufficiency, SIGNAL_NODES + ["build_error_response"]
    )

    for node in SIGNAL_NODES:
        graph.add_edge(node, "aggregate_composite_signal")

    graph.add_edge("aggregate_composite_signal", "build_success_response")
    graph.add_edge("build_success_response", "persist_results")
    graph.add_edge("persist_results", END)
    graph.add_edge("build_error_response", END)

    return graph.compile()
