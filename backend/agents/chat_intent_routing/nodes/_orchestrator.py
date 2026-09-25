"""Runs the Orchestrator Subgraph (agents/orchestrator/graph.py) for one ticker.

Shared by the analyze_stock tool (chat) and direct_analysis (a caller-supplied
ticker). The Orchestrator compiles with its own MemorySaver, which its
request_human_review interrupt() needs: each call gets a fresh thread_id, any
pause is auto-approved (this layer has no reviewer-facing surface yet), and the
thread is deleted afterwards -- a MemorySaver keeps every thread forever
otherwise, so memory would grow with every request.

An exception out of the Orchestrator is caught and returned in the same
error_response shape its own build_error_response.py uses, so an
infrastructure failure one layer down is a normal error, not a crash.
"""

import uuid

from langgraph.types import Command

from agents.orchestrator.graph import build_graph as build_orchestrator_graph

_orchestrator_graph = build_orchestrator_graph()


def run_orchestrator(ticker, horizon=None, forecast_days=None):
    """-> (orchestrator_result, response): the Orchestrator's final state (None
    if it raised) and its final_response or error_response."""
    request = {"ticker": ticker, "horizon": horizon}
    if forecast_days is not None:
        request["forecast_days"] = forecast_days

    thread_id = str(uuid.uuid4())
    thread_config = {"configurable": {"thread_id": thread_id}}
    try:
        result = _orchestrator_graph.invoke(request, config=thread_config)

        for task in _orchestrator_graph.get_state(thread_config).tasks:
            if task.interrupts:
                result = _orchestrator_graph.invoke(
                    Command(resume={"reviewer_decision": "approve", "review_notes": None}),
                    config=thread_config,
                )
                break
    except Exception as exc:
        return None, {"ticker": ticker, "reason": f"orchestrator failed: {exc}"}
    finally:
        _orchestrator_graph.checkpointer.delete_thread(thread_id)

    return result, result.get("final_response") or result.get("error_response")
