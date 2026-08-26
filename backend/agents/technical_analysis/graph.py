from langgraph.graph import END, START, StateGraph

from .nodes.aggregate_technical_signal import aggregate_technical_signal
from .nodes.build_error_response import build_error_response
from .nodes.build_final_response import build_final_response
from .nodes.calculate_rrr import calculate_rrr
from .nodes.check_prior_trend_alignment import check_prior_trend_alignment
from .nodes.check_volume_confirmation import check_volume_confirmation
from .nodes.compute_momentum import compute_momentum
from .nodes.compute_support_resistance import compute_support_resistance
from .nodes.compute_trend import compute_trend
from .nodes.compute_volatility import compute_volatility
from .nodes.derive_stoploss_and_target import derive_stoploss_and_target
from .nodes.detect_candlestick_pattern import detect_candlestick_pattern
from .nodes.fetch_price_history import fetch_price_history
from .nodes.persist_results import persist_results
from .nodes.validate_input import validate_input
from .state import TechnicalAnalysisState

INDICATOR_NODES = [
    "compute_trend",
    "compute_momentum",
    "compute_volatility",
    "compute_support_resistance",
]


def route_after_validate(state: TechnicalAnalysisState) -> str:
    return "fetch_price_history" if state.get("is_valid") else "build_error_response"


def route_after_fetch(state: TechnicalAnalysisState):
    if state.get("fetch_failed"):
        return ["build_error_response"]
    return INDICATOR_NODES


def route_after_pattern(state: TechnicalAnalysisState) -> str:
    return "check_prior_trend_alignment" if state.get("candlestick_pattern") else "build_final_response"


def route_after_trend_alignment(state: TechnicalAnalysisState) -> str:
    prior_trend_ok = state.get("prior_trend_ok") or {}
    return "check_volume_confirmation" if prior_trend_ok.get("passed") else "build_final_response"


def route_after_volume(state: TechnicalAnalysisState) -> str:
    volume_ok = state.get("volume_ok") or {}
    return "derive_stoploss_and_target" if volume_ok.get("passed") else "build_final_response"


def build_graph():
    graph = StateGraph(TechnicalAnalysisState)

    graph.add_node("validate_input", validate_input)
    graph.add_node("fetch_price_history", fetch_price_history)
    graph.add_node("build_error_response", build_error_response)
    graph.add_node("compute_trend", compute_trend)
    graph.add_node("compute_momentum", compute_momentum)
    graph.add_node("compute_volatility", compute_volatility)
    graph.add_node("compute_support_resistance", compute_support_resistance)
    graph.add_node("aggregate_technical_signal", aggregate_technical_signal)
    graph.add_node("detect_candlestick_pattern", detect_candlestick_pattern)
    graph.add_node("check_prior_trend_alignment", check_prior_trend_alignment)
    graph.add_node("check_volume_confirmation", check_volume_confirmation)
    graph.add_node("derive_stoploss_and_target", derive_stoploss_and_target)
    graph.add_node("calculate_rrr", calculate_rrr)
    graph.add_node("build_final_response", build_final_response)
    graph.add_node("persist_results", persist_results)

    graph.add_edge(START, "validate_input")

    graph.add_conditional_edges(
        "validate_input", route_after_validate, ["fetch_price_history", "build_error_response"]
    )
    graph.add_conditional_edges(
        "fetch_price_history", route_after_fetch, INDICATOR_NODES + ["build_error_response"]
    )

    for node in INDICATOR_NODES:
        graph.add_edge(node, "aggregate_technical_signal")

    graph.add_edge("aggregate_technical_signal", "detect_candlestick_pattern")

    graph.add_conditional_edges(
        "detect_candlestick_pattern",
        route_after_pattern,
        ["check_prior_trend_alignment", "build_final_response"],
    )
    graph.add_conditional_edges(
        "check_prior_trend_alignment",
        route_after_trend_alignment,
        ["check_volume_confirmation", "build_final_response"],
    )
    graph.add_conditional_edges(
        "check_volume_confirmation",
        route_after_volume,
        ["derive_stoploss_and_target", "build_final_response"],
    )

    graph.add_edge("derive_stoploss_and_target", "calculate_rrr")
    graph.add_edge("calculate_rrr", "build_final_response")
    graph.add_edge("build_final_response", "persist_results")
    graph.add_edge("persist_results", END)
    graph.add_edge("build_error_response", END)

    return graph.compile()
