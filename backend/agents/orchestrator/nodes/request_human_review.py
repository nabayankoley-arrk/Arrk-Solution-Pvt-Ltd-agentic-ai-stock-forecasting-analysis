"""request_human_review — conditional pause node.

Reached only when reconcile_and_decide finalizes with requires_review =
True (pillar disagreement, an unresolved pillar failure, or a
loop-guard-forced finalize -- see reconcile_and_decide.py). Uses
LangGraph's interrupt() to pause the run; build_graph() must compile with
a checkpointer for this to work (see graph.py) -- interrupt() raises a
GraphInterrupt the first time this node runs, which the checkpointer lets
LangGraph recover from on resume instead of restarting the whole run.

HUMAN_REVIEW_TIMEOUT has no effect inside this node: a paused interrupt()
has no running Python call left to attach a timer to. Enforcing it
(marking a run "pending"/expired after too long) is left to whichever
external caller/API resumes runs -- see config.py's docstring on that
constant.

Resume payload (passed to `graph.invoke(Command(resume=...), config=...)`):
    {"reviewer_decision": "approve" | "edit" | "rerun",
     "review_notes": str | None,       # optional edited narrative
     "selected_tool": str | None,      # required if reviewer_decision == "rerun"
     "tool_call_args": dict | None}
"""

from langgraph.types import interrupt


def request_human_review(state):
    review_request = {
        "ticker": state.get("ticker"),
        "horizon": state.get("horizon"),
        "decision": state.get("decision"),
        "reason": state.get("reason"),
        "technical_analysis": state.get("technical_analysis"),
        "fundamental_analysis": state.get("fundamental_analysis"),
        "sentiment_analysis": state.get("sentiment_analysis"),
        "pillar_status": state.get("pillar_status"),
        "errors": state.get("errors"),
    }
    resume = interrupt(review_request)

    reviewer_decision = resume.get("reviewer_decision")
    updates = {
        "reviewer_decision": reviewer_decision,
        "review_notes": resume.get("review_notes"),
    }

    if reviewer_decision == "rerun":
        updates["selected_tool"] = resume.get("selected_tool")
        updates["tool_call_args"] = resume.get("tool_call_args") or {}
        updates["loop_guard_override"] = True

    return updates
