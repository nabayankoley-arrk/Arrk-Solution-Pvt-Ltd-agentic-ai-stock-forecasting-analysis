"""route_to_orchestrator — stock/market intent handler.

Invokes the Orchestrator Subgraph (agents/orchestrator/graph.py) for the
ticker/horizon/forecast_days this subgraph resolved, now that the
Orchestrator Subgraph itself no longer knows about user_id/user_memory
(see that package's state.py/graph.py) -- memory is entirely this
subgraph's concern.

Only reached when parse_and_route's intent is 'stock_market' (see
graph.py's conditional edge). An unresolved ticker still reaches here (see
parse_and_route's own docstring) and comes back as the Orchestrator
Subgraph's own "ticker is required" error_response rather than a special
case handled here.

The Orchestrator Subgraph compiles with its own MemorySaver checkpointer
and its own thread_id (see build_orchestrator_graph, generated fresh per
call) -- it stays a black box invoked at arm's length, not a nested
subgraph sharing this graph's checkpointer, since it can pause mid-run for
request_human_review and this subgraph has no reviewer-facing surface of
its own yet. A pause is auto-approved here for that reason; revisit once
this layer can expose a pending review to a caller instead of always
approving on its behalf.

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

    thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
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

    response = result.get("final_response") or result.get("error_response")
    return {"orchestrator_result": result, "response": response}
