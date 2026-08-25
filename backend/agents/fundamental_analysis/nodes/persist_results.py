"""persist_results — terminal node.

Writes the completed analysis to fundamental_analysis_results so a later
request for the same ticker/day can be served from that cached row instead
of recomputing all four signals (see docs/fundamental-analysis-design.md
Section 4.2). Only reached after build_success_response on the success
path (see graph.py) -- build_error_response has no data_tier/signals to
persist, so it skips this node entirely.

Everything needed is already merged into `final_output` by
build_success_response, so this reads from there rather than the raw
per-signal state fields.
"""

from db.upsert import save_fundamental_analysis_results


def persist_results(state):
    final_output = state.get("final_output") or {}
    relative_valuation = final_output.get("relative_valuation") or {}
    growth = final_output.get("growth") or {}
    financial_health = final_output.get("financial_health") or {}
    analyst_consensus = final_output.get("analyst_consensus") or {}
    composite = final_output.get("composite") or {}

    record = {
        "ticker": final_output.get("ticker"),
        "as_of_date": final_output.get("as_of_date"),
        "data_tier": final_output.get("data_tier"),
        "relative_valuation_class": relative_valuation.get("classification"),
        "relative_valuation_detail": relative_valuation.get("detail"),
        "growth_class": growth.get("classification"),
        "growth_detail": growth.get("detail"),
        "financial_health_class": financial_health.get("classification"),
        "financial_health_detail": financial_health.get("detail"),
        "analyst_consensus_class": analyst_consensus.get("classification"),
        "analyst_consensus_detail": analyst_consensus.get("detail"),
        "composite_direction": composite.get("direction"),
        "composite_confidence": composite.get("confidence"),
        "risk_flags": composite.get("risk_flags") or [],
    }
    save_fundamental_analysis_results(record)
    return {}
