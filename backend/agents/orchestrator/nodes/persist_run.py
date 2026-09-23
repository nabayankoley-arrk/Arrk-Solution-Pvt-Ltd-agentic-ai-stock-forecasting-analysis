"""persist_run — terminal node.

Writes the completed run to orchestrator_runs -- unqualified, so the
public schema, which is where db/schema.sql creates it -- mirroring
each pillar subgraph's own persist_results.py convention. Reached after
both build_final_response (the success path, including after human
review) and build_error_response (invalid input) -- see graph.py -- so
every run leaves an audit row, not just successful ones.

Upserts on run_id (see db.upsert.save_orchestrator_run), so a run that
paused for human review and was later resumed updates the same row rather
than creating a second one.
"""

from db.upsert import save_orchestrator_run


def persist_run(state):
    pillar_status = state.get("pillar_status") or {}
    error_response = state.get("error_response")
    errors = {pillar: reason for pillar, reason in (state.get("errors") or {}).items() if reason}

    record = {
        "run_id": state.get("run_id"),
        "ticker": state.get("ticker") or "unknown",
        "analysis_horizon": state.get("horizon") or "unknown",
        "technical_status": pillar_status.get("technical"),
        "fundamental_status": pillar_status.get("fundamental"),
        "sentiment_status": pillar_status.get("sentiment"),
        "selected_tool": state.get("selected_tool"),
        "tool_loop_count": state.get("tool_loop_count", 0),
        "final_decision": state.get("decision") or ("invalid_input" if error_response else None),
        "final_response": state.get("final_response"),
        "error_details": error_response or (errors or None),
        "requires_review": bool(state.get("requires_review", False)),
        "reviewer_decision": state.get("reviewer_decision"),
        "review_notes": state.get("review_notes"),
    }
    save_orchestrator_run(record)
    return {}
