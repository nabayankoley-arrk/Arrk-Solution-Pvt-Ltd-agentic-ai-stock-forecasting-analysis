"""check_volume_confirmation — guard node.

Compares the latest day's volume against the average of the VOLUME_LOOKBACK
days before it. Passes if the ratio meets VOLUME_CONFIRMATION_RATIO.
"""

from ..config import VOLUME_CONFIRMATION_RATIO, VOLUME_LOOKBACK


def check_volume_confirmation(state):
    history = state.get("price_history") or []
    volumes = [row["volume"] for row in history if row.get("volume") is not None]

    if len(volumes) < VOLUME_LOOKBACK + 1:
        return {
            "volume_ok": {
                "passed": False,
                "volume_ratio": None,
                "reason": "insufficient volume history to confirm the pattern",
            }
        }

    latest_volume = volumes[-1]
    baseline = volumes[-(VOLUME_LOOKBACK + 1):-1]
    avg_volume = sum(baseline) / len(baseline)

    if not avg_volume:
        return {
            "volume_ok": {
                "passed": False,
                "volume_ratio": None,
                "reason": "average volume is zero over the lookback window",
            }
        }

    volume_ratio = round(latest_volume / avg_volume, 4)
    passed = volume_ratio >= VOLUME_CONFIRMATION_RATIO
    reason = None
    if not passed:
        reason = (
            f"latest volume is only {round(volume_ratio, 2)}x the {VOLUME_LOOKBACK}-day "
            f"average (need >= {VOLUME_CONFIRMATION_RATIO}x)"
        )
    return {"volume_ok": {"passed": passed, "volume_ratio": volume_ratio, "reason": reason}}
