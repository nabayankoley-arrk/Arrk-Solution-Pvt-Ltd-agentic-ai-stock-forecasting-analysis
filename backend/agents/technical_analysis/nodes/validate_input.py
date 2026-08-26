"""validate_input — guard node.

Confirms `ticker` is well-formed and, if `lookback_days` is missing,
applies the default from config. See the Technical Analysis Subgraph
specification, node `validate_input`.
"""

from ..config import LOOKBACK_DAYS


def validate_input(state):
    ticker = state.get("ticker")
    lookback_days = state.get("lookback_days")

    if not ticker or not isinstance(ticker, str):
        return {"is_valid": False, "validation_error": "ticker is required and must be a string"}

    if lookback_days is None:
        lookback_days = LOOKBACK_DAYS
    elif not isinstance(lookback_days, int) or isinstance(lookback_days, bool) or lookback_days <= 0:
        return {"is_valid": False, "validation_error": "lookback_days must be a positive integer"}

    return {"is_valid": True, "validation_error": None, "lookback_days": lookback_days}
