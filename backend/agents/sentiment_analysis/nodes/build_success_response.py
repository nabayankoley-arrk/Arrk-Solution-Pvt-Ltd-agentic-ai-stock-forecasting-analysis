"""build_success_response — terminal node.

Assembles the composite call, thematic summary, and citations into the
final payload, per the specification's Final Response section:
ticker, overall call, source-level breakdown, recency-weighted
confidence, citations, and availability status per source (which feeds
the Orchestrator's own pillar_status -- see
agents/orchestrator/nodes/_pillar_runners.run_sentiment).
"""

import datetime

_SOURCE_LABELS = {"transcript": "Transcript tone", "annual_report": "Annual report"}


def _thematic_summary(state):
    parts = []
    for source, state_key in (("transcript", "transcript_tone"), ("annual_report", "annual_report_sentiment")):
        score = state.get(state_key)
        if not score or not score.get("label"):
            continue
        rationale = score.get("rationale") or ""
        parts.append(f"{_SOURCE_LABELS[source]} ({score['label']}): {rationale}".strip())

    if not parts:
        return "No transcript or annual-report sentiment was available for this ticker."
    return " ".join(parts)


def build_success_response(state):
    combined = state.get("combined_sentiment") or {}
    pillar_status = state.get("pillar_status") or {}

    final_output = {
        "ticker": state.get("ticker"),
        "as_of_date": datetime.date.today().isoformat(),
        "direction": combined.get("direction"),
        "confidence": combined.get("confidence"),
        "summary": _thematic_summary(state),
        "source_breakdown": combined.get("source_breakdown"),
        "citations": combined.get("citations"),
        "source_status": {
            "transcript": pillar_status.get("transcript"),
            "annual_report": pillar_status.get("annual_report"),
        },
    }
    return {"final_output": final_output}
