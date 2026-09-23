"""validate_input — guard node.

Confirms `ticker` is present, matching the specification's "Validates the
ticker before any retrieval happens" (Reads: ticker). No horizon/other
input here -- see state.py, this subgraph takes only a ticker.
"""


def validate_input(state):
    ticker = state.get("ticker")
    if not ticker or not isinstance(ticker, str):
        return {"is_valid": False, "validation_error": "ticker is required and must be a string"}
    return {"is_valid": True, "validation_error": None}
