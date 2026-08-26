"""derive_stoploss_and_target — trade-setup node.

Only reached after check_prior_trend_alignment and check_volume_confirmation
have both passed (see graph.py's routing). Entry is the latest close.
Stop-loss comes from the candlestick pattern's own low (bullish setups) or
high (bearish setups); target is the nearest resistance (bullish) or
support (bearish). A setup is rejected (entry/stop_loss/target all None)
if either level lands on the wrong side of entry, or if the stop-loss
sits farther than SR_TOLERANCE_PERCENT from the opposing support/
resistance level -- a pattern-derived stop that isn't anchored near a
real technical level isn't a technically meaningful invalidation point.
"""

from ..config import SR_TOLERANCE_PERCENT

_REJECTED = {"entry_price": None, "stop_loss": None, "target": None}


def derive_stoploss_and_target(state):
    history = state.get("price_history") or []
    closes = [row["close_price"] for row in history]
    entry_price = closes[-1] if closes else None

    pattern = state.get("candlestick_pattern") or {}
    direction = state.get("pattern_direction")
    support_resistance = state.get("support_resistance") or {}
    support = support_resistance.get("support")
    resistance = support_resistance.get("resistance")

    if entry_price is None or direction not in ("bullish", "bearish") or not pattern:
        return dict(_REJECTED, entry_price=entry_price)

    if direction == "bullish":
        stop_loss = pattern.get("low")
        target = resistance
        reference_level = support
    else:
        stop_loss = pattern.get("high")
        target = support
        reference_level = resistance

    if stop_loss is None or target is None:
        return dict(_REJECTED, entry_price=entry_price)

    if direction == "bullish" and not (stop_loss < entry_price < target):
        return dict(_REJECTED, entry_price=entry_price)
    if direction == "bearish" and not (target < entry_price < stop_loss):
        return dict(_REJECTED, entry_price=entry_price)

    if reference_level:
        distance_pct = abs(stop_loss - reference_level) / reference_level * 100
        if distance_pct > SR_TOLERANCE_PERCENT:
            return dict(_REJECTED, entry_price=entry_price)

    return {"entry_price": entry_price, "stop_loss": stop_loss, "target": target}
