"""route_to_orchestrator — stock/market intent handler.

Invokes the Orchestrator Subgraph (agents/orchestrator/graph.py) for the
ticker/horizon/forecast_days this subgraph resolved.

Only reached when interpret's action is 'analyze' (see graph.py), with a
resolved_ticker already validated against `universe`.

The Orchestrator Subgraph compiles with its own MemorySaver checkpointer,
which its request_human_review interrupt() needs. Each call gets a fresh
thread_id, any pause is auto-approved (this layer has no reviewer-facing
surface yet), and the thread is deleted afterwards -- a MemorySaver keeps
every thread forever otherwise, so memory would grow with every request.

An unexpected exception out of the Orchestrator Subgraph itself (as
opposed to its own normal validation error_response, which is just a
regular return value) is caught here and turned into the same
error_response shape build_error_response.py uses -- so a bug or an
unhandled infrastructure failure one layer down surfaces to the caller as
a normal error response instead of taking down this entire subgraph.
"""

import uuid

from langgraph.types import Command

from agents.orchestrator.graph import build_graph as build_orchestrator_graph

_orchestrator_graph = build_orchestrator_graph()


def route_to_orchestrator(state):
    ticker = state.get("resolved_ticker")
    request = {"ticker": ticker, "horizon": state.get("horizon")}
    forecast_days = state.get("forecast_days")
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
        error_response = {"ticker": ticker, "reason": f"orchestrator failed: {exc}"}
        return {"orchestrator_result": None, "response": error_response}
    finally:
        _orchestrator_graph.checkpointer.delete_thread(thread_id)

    response = result.get("final_response") or result.get("error_response")
    return {"orchestrator_result": result, "response": response}
