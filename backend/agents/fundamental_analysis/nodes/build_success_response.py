"""build_success_response — terminal node.

Merges `ticker`, `as_of_date`, `data_tier`, and `composite_result` into the
final payload. See docs/fundamental-analysis-design.md Section 3.2, row
`build_success_response`.
"""


def build_success_response(state):
    final_output = {
        "ticker": state.get("ticker"),
        "as_of_date": state.get("as_of_date"),
        "data_tier": state.get("data_tier"),
        "relative_valuation": state.get("relative_valuation"),
        "growth": state.get("growth"),
        "financial_health": state.get("financial_health"),
        "analyst_consensus": state.get("analyst_consensus"),
        "composite": state.get("composite_result"),
    }
    return {"final_output": final_output}
