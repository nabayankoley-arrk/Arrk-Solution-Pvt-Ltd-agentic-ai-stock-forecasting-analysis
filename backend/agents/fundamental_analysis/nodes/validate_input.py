"""validate_input — guard node.

Confirms `ticker` is well-formed, `ratio_basis` is TTM or MRQ, and
`lookback_years` is a positive integer. See
docs/fundamental-analysis-design.md Section 3.2, row `validate_input`.
"""

from ..config import VALID_RATIO_BASES


def validate_input(state):
    ticker = state.get("ticker")
    ratio_basis = state.get("ratio_basis")
    lookback_years = state.get("lookback_years")

    if not ticker or not isinstance(ticker, str):
        return {"is_valid": False, "validation_error": "ticker is required and must be a string"}

    if ratio_basis not in VALID_RATIO_BASES:
        return {
            "is_valid": False,
            "validation_error": f"ratio_basis must be one of {VALID_RATIO_BASES}, got {ratio_basis!r}",
        }

    if not isinstance(lookback_years, int) or isinstance(lookback_years, bool) or lookback_years <= 0:
        return {"is_valid": False, "validation_error": "lookback_years must be a positive integer"}

    return {"is_valid": True, "validation_error": None}
