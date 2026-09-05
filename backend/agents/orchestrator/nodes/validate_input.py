"""validate_input — guard node.

Confirms `ticker` is present and `horizon` (if supplied) is one of
config.VALID_HORIZONS, defaulting horizon to config.DEFAULT_HORIZON when
omitted. Invalid requests are routed to build_error_response by
graph.py's route_after_validate; this node only decides is_valid/
validation_error, it doesn't build the error payload itself.

When the caller didn't supply a ticker, falls back to the most recent
entry in user_memory["watchlist"] (set by load_user_memory, which runs
before this node -- see graph.py) before giving up -- the User Memory
extension's "Memory-Informed Routing" behavior, ported over from the
not-yet-implemented Chat Intent & Routing base subgraph's parse_and_route.
Absent a resolved ticker either way, this is still a validation error.
The resolved ticker is written back into state so every downstream node
(and update_user_memory's watchlist update) sees the same value.

Also resolves horizon into each pillar subgraph's own request shape
(lookback_days for Technical, ratio_basis/lookback_years for
Fundamental) -- see config.HORIZON_TO_PILLAR_PARAMS and state.py's note
on why this stays out of the orchestrator's documented cross-pillar
state -- and initializes the counters/accumulators/identifiers the rest
of the graph expects to already exist (run_id, pillar_status, errors,
tool_loop_count).

forecast_days (optional; see state.py's note on that field) is validated
here the same way forecast_price_range.py itself validates it -- a
positive integer -- so a bad value fails fast at the graph's entry point
instead of surfacing later as an LLMAgentError/ValueError out of
build_final_response.
"""

import uuid

from ..config import DEFAULT_HORIZON, HORIZON_TO_PILLAR_PARAMS, VALID_HORIZONS


def validate_input(state):
    run_id = str(uuid.uuid4())

    ticker = state.get("ticker")
    if not ticker or not isinstance(ticker, str):
        watchlist = (state.get("user_memory") or {}).get("watchlist") or []
        ticker = watchlist[0] if watchlist else None
    if not ticker or not isinstance(ticker, str):
        return {"run_id": run_id, "is_valid": False, "validation_error": "ticker is required and must be a string"}

    horizon = state.get("horizon") or DEFAULT_HORIZON
    if horizon not in VALID_HORIZONS:
        return {
            "run_id": run_id,
            "is_valid": False,
            "validation_error": f"horizon must be one of {VALID_HORIZONS}, got {horizon!r}",
        }

    forecast_days = state.get("forecast_days")
    if forecast_days is not None and (
        not isinstance(forecast_days, int) or isinstance(forecast_days, bool) or forecast_days <= 0
    ):
        return {
            "run_id": run_id,
            "is_valid": False,
            "validation_error": f"forecast_days must be a positive integer, got {forecast_days!r}",
        }

    pillar_params = HORIZON_TO_PILLAR_PARAMS[horizon]
    return {
        "run_id": run_id,
        "is_valid": True,
        "validation_error": None,
        "ticker": ticker,
        "horizon": horizon,
        "lookback_days": pillar_params["lookback_days"],
        "ratio_basis": pillar_params["ratio_basis"],
        "lookback_years": pillar_params["lookback_years"],
        "pillar_status": {},
        "errors": {},
        "tool_loop_count": 0,
        "loop_guard_override": False,
    }
