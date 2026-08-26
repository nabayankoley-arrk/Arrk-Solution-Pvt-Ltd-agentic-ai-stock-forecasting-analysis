"""build_error_response — terminal node.

Produces the error output for bad input, fetch failure, or insufficient
history. See docs/fundamental-analysis-design.md Section 3.2, row
`build_error_response`.
"""


def build_error_response(state):
    if state.get("validation_error"):
        reason = state["validation_error"]
    elif state.get("fetch_error"):
        reason = state["fetch_error"]
    elif state.get("data_tier") == "insufficient":
        reason = "insufficient fundamentals history for analysis"
    else:
        reason = "unknown error"

    error = {"ticker": state.get("ticker"), "reason": reason}
    return {"error": error, "final_output": {"error": error}}
