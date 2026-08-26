"""build_error_response — terminal node.

Produces the error output for bad input or a price-history fetch failure
(including "not enough rows to analyze" -- see fetch_price_history.py).
"""


def build_error_response(state):
    if state.get("validation_error"):
        reason = state["validation_error"]
    elif state.get("fetch_error"):
        reason = state["fetch_error"]
    else:
        reason = "unknown error"

    error = {"ticker": state.get("ticker"), "reason": reason}
    return {"error": error, "final_output": {"error": error}}
