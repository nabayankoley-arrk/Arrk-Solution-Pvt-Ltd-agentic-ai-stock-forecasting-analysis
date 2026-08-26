"""build_final_response — terminal node.

Reached from four different points in the graph (no pattern detected,
trend misalignment, insufficient volume, or a fully evaluated RRR --
see graph.py's routing), so `trade_setup` may or may not already be set
by calculate_rrr. When it isn't, this reconstructs the appropriate
not_applicable/rejected status from whichever guard short-circuited.
"""


def build_final_response(state):
    trade_setup = state.get("trade_setup")
    if trade_setup is None:
        trade_setup = _early_exit_trade_setup(state)

    price_history = state.get("price_history") or []
    current_price = price_history[-1]["close_price"] if price_history else None

    final_output = {
        "ticker": state.get("ticker"),
        "as_of_date": state.get("as_of_date"),
        "current_price": current_price,
        "technical_signal": state.get("technical_signal"),
        "confidence": state.get("confidence"),
        "support_resistance": state.get("support_resistance"),
        "candlestick_pattern": state.get("candlestick_pattern"),
        "pattern_direction": state.get("pattern_direction"),
        "trade_setup": trade_setup,
    }
    return {"final_output": final_output}


def _early_exit_trade_setup(state):
    pattern = state.get("candlestick_pattern")
    if not pattern:
        return {"status": "not_applicable", "reason": "no candlestick pattern detected"}

    prior_trend_ok = state.get("prior_trend_ok")
    if prior_trend_ok and not prior_trend_ok.get("passed"):
        return {"status": "rejected", "reason": prior_trend_ok.get("reason")}

    volume_ok = state.get("volume_ok")
    if volume_ok and not volume_ok.get("passed"):
        return {"status": "rejected", "reason": volume_ok.get("reason")}

    return {"status": "not_applicable", "reason": "trade setup not evaluated"}
