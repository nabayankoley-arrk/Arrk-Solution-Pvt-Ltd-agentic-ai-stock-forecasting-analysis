"""Assembles the Sentiment Analysis Agent's request-time graph.

    validate_input
       |- invalid -> build_error_response -> END
       `- valid   -> fetch_transcript    -> score_transcript    -\\
                     fetch_annual_report -> score_annual_report -+-> combine_sentiment_signals -> build_success_response -> END

The two source chains run in parallel and join before combine_sentiment_signals.
A score node reads the document's stored sentiment profile and calls the LLM
only when it is missing or out of date (see nodes/_score_helpers.py).
"""

from langgraph.graph import END, START, StateGraph

from .nodes.build_error_response import build_error_response
from .nodes.build_success_response import build_success_response
from .nodes.combine_sentiment_signals import combine_sentiment_signals
from .nodes.fetch_annual_report import fetch_annual_report
from .nodes.fetch_transcript import fetch_transcript
from .nodes.score_annual_report import score_annual_report
from .nodes.score_transcript import score_transcript
from .nodes.validate_input import validate_input
from .state import SentimentAnalysisState

FETCH_NODES = ["fetch_transcript", "fetch_annual_report"]


def route_after_validate(state: SentimentAnalysisState):
    return FETCH_NODES if state.get("is_valid") else ["build_error_response"]


def build_graph():
    graph = StateGraph(SentimentAnalysisState)

    graph.add_node("validate_input", validate_input)
    graph.add_node("fetch_transcript", fetch_transcript)
    graph.add_node("fetch_annual_report", fetch_annual_report)
    graph.add_node("score_transcript", score_transcript)
    graph.add_node("score_annual_report", score_annual_report)
    graph.add_node("combine_sentiment_signals", combine_sentiment_signals)
    graph.add_node("build_success_response", build_success_response)
    graph.add_node("build_error_response", build_error_response)

    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges(
        "validate_input", route_after_validate, FETCH_NODES + ["build_error_response"]
    )

    graph.add_edge("fetch_transcript", "score_transcript")
    graph.add_edge("fetch_annual_report", "score_annual_report")
    graph.add_edge("score_transcript", "combine_sentiment_signals")
    graph.add_edge("score_annual_report", "combine_sentiment_signals")
    graph.add_edge("combine_sentiment_signals", "build_success_response")

    graph.add_edge("build_success_response", END)
    graph.add_edge("build_error_response", END)

    return graph.compile()
