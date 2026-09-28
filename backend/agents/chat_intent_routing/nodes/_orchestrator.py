"""Runs the Orchestrator Subgraph (agents/orchestrator/graph.py) for one ticker.

Shared by the analyze_stock tool (chat) and direct_analysis (a caller-supplied
ticker). The Orchestrator no longer pauses for a human review -- pillar
disagreement comes back in its verdict's conflicts -- so it runs as one plain
invoke with no checkpointer or thread to clean up.

An exception out of the Orchestrator is caught and returned in the same
error_response shape its own build_error_response.py uses, so an
infrastructure failure one layer down is a normal error, not a crash.
"""

from agents.orchestrator.graph import build_graph as build_orchestrator_graph

_orchestrator_graph = build_orchestrator_graph()


def run_orchestrator(ticker, horizon=None, forecast_days=None):
    """-> (orchestrator_result, response): the Orchestrator's final state (None
    if it raised) and its final_response or error_response. Without a horizon,
    the Orchestrator derives one from forecast_days, else uses its default."""
    request = {"ticker": ticker, "horizon": horizon}
    if forecast_days is not None:
        request["forecast_days"] = forecast_days
    try:
        result = _orchestrator_graph.invoke(request)
    except Exception as exc:
        return None, {"ticker": ticker, "reason": f"orchestrator failed: {exc}"}
    return result, result.get("final_response") or result.get("error_response")
