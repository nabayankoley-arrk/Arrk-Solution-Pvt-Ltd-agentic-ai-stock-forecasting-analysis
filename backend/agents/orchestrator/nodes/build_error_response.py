"""build_error_response — terminal node.

Produces the standardized error response for invalid orchestrator input.
Baseline pillar failures don't reach this node -- fetch_technical_analysis/
fetch_fundamental_analysis/fetch_sentiment_analysis always return a result
(each pillar subgraph has its own build_error_response, or -- for
Sentiment, until it's implemented -- a fixed "unavailable" stub); those
failures instead flow into pillar_status/errors for reconcile_and_decide
to account for.
"""


def build_error_response(state):
    error_response = {"ticker": state.get("ticker"), "reason": state.get("validation_error")}
    return {"error_response": error_response}
