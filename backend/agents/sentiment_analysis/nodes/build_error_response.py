"""build_error_response — terminal node.

Builds the standardized response for an invalid ticker, per the
specification's build_error_response node description. This is the only
route into this node -- an unavailable transcript/annual-report source is
not an error (see combine_sentiment_signals.py's docstring); it still
reaches build_success_response with direction=None.
"""


def build_error_response(state):
    reason = state.get("validation_error") or "unknown error"
    error = {"ticker": state.get("ticker"), "reason": reason}
    return {
        "error": error,
        "final_output": {
            "ticker": state.get("ticker"),
            "as_of_date": None,
            "direction": None,
            "confidence": None,
            "summary": None,
            "error": error,
        },
    }
