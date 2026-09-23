"""Assembles the Sentiment Analysis Agent's Request-Time Subgraph.

Implements only the transcript and annual-report sources -- see
__init__.py for why news/coverage-report are out of scope. Control flow
mirrors the specification's Request-Time Subgraph edges for the sources
that remain:

    validate_input
       |- invalid -> build_error_response -> END
       `- valid   -> fetch_transcript ------> score_transcript_tone      -\\
                     fetch_annual_report ---> score_annual_report_sentiment -+-> combine_sentiment_signals -> build_success_response -> END

The two source chains run independently and are joined by LangGraph's own
superstep synchronization before combine_sentiment_signals runs -- the
same fan-out/fan-in pattern used by the Technical and Fundamental
Analysis Agents' own graphs (see agents/technical_analysis/graph.py,
agents/fundamental_analysis/graph.py) and by the Orchestrator's three
baseline pillar fetches.
"""

from langgraph.graph import END, START, StateGraph

from .nodes.build_error_response import build_error_response
from .nodes.build_success_response import build_success_response
from .nodes.combine_sentiment_signals import combine_sentiment_signals
from .nodes.fetch_annual_report import fetch_annual_report
from .nodes.fetch_transcript import fetch_transcript
from .nodes.score_annual_report_sentiment import score_annual_report_sentiment
from .nodes.score_transcript_tone import score_transcript_tone
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
    graph.add_node("score_transcript_tone", score_transcript_tone)
    graph.add_node("score_annual_report_sentiment", score_annual_report_sentiment)
    graph.add_node("combine_sentiment_signals", combine_sentiment_signals)
    graph.add_node("build_success_response", build_success_response)
    graph.add_node("build_error_response", build_error_response)

    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges(
        "validate_input", route_after_validate, FETCH_NODES + ["build_error_response"]
    )

    graph.add_edge("fetch_transcript", "score_transcript_tone")
    graph.add_edge("fetch_annual_report", "score_annual_report_sentiment")
    graph.add_edge("score_transcript_tone", "combine_sentiment_signals")
    graph.add_edge("score_annual_report_sentiment", "combine_sentiment_signals")
    graph.add_edge("combine_sentiment_signals", "build_success_response")

    graph.add_edge("build_success_response", END)
    graph.add_edge("build_error_response", END)

    return graph.compile()
