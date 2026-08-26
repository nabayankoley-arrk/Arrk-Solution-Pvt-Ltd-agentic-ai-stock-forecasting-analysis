"""calculate_rrr — trade-validation node.

Computes risk (entry vs. stop-loss distance) and reward (entry vs. target
distance), derives the risk-reward ratio, and writes `trade_setup` with a
'validated' or 'rejected' status -- both outcomes route to
build_final_response (see graph.py); only the status/reason differ.
"""

from ..config import MIN_RRR


def calculate_rrr(state):
    entry_price = state.get("entry_price")
    stop_loss = state.get("stop_loss")
    target = state.get("target")

    if entry_price is None or stop_loss is None or target is None:
        return _setup(
            entry_price, stop_loss, target, None,
            "rejected", "stop-loss or target could not be derived from the detected pattern",
        )

    risk = abs(entry_price - stop_loss)
    reward = abs(target - entry_price)

    if risk == 0:
        return _setup(
            entry_price, stop_loss, target, None,
            "rejected", "stop-loss equals entry price -- risk is zero",
        )

    rrr = round(reward / risk, 2)
    if rrr < MIN_RRR:
        return _setup(
            entry_price, stop_loss, target, rrr,
            "rejected", f"risk-reward ratio {rrr} is below the minimum threshold {MIN_RRR}",
        )

    return _setup(entry_price, stop_loss, target, rrr, "validated", None)


def _setup(entry_price, stop_loss, target, rrr, status, reason):
    trade_setup = {
        "status": status,
        "reason": reason,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target": target,
        "rrr": rrr,
    }
    return {"rrr": rrr, "trade_setup": trade_setup}
