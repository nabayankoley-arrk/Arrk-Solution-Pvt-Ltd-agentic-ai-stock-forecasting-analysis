"""invoke_orchestrator — bridges the User Memory extension into the
Orchestrator Subgraph.

Temporary stand-in for the real Chat Intent & Routing base subgraph's
`parse_and_route` node (see this package's __init__.py) -- there is no
chat-message parsing here, only a direct pass-through of ticker/horizon/
forecast_days into the already-built Orchestrator Subgraph
(agents/orchestrator/graph.py), which is where the actual Technical/
Fundamental/Sentiment analysis and reconciliation happen.

The Orchestrator pauses for human review (via langgraph.types.interrupt)
whenever a pillar is unhealthy or pillars disagree -- see
orchestrator/nodes/request_human_review.py. Auto-approves that pause here
so this node still returns a single final response per call, mirroring
the orchestrator's own smoke_test.py's run_and_approve helper. Swap this
for a real human-in-the-loop flow later if this endpoint needs one.
"""

import uuid

from langgraph.types import Command

from ...orchestrator.graph import build_graph as build_orchestrator_graph

_orchestrator_graph = build_orchestrator_graph()


def _pending_interrupt(thread_config):
    for task in _orchestrator_graph.get_state(thread_config).tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


def invoke_orchestrator(state):
    thread_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    request = {
        key: state[key]
        for key in ("ticker", "horizon", "forecast_days", "user_id")
        if state.get(key) is not None
    }

    result = _orchestrator_graph.invoke(request, config=thread_config)

    if _pending_interrupt(thread_config) is not None:
        result = _orchestrator_graph.invoke(
            Command(resume={"reviewer_decision": "approve", "review_notes": None}),
            config=thread_config,
        )

    final_response = result.get("final_response")
    return {
        "resolved_ticker": (final_response or {}).get("ticker") or state.get("ticker"),
        "final_response": final_response,
        "error_response": result.get("error_response"),
    }
