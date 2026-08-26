"""compute_analyst_consensus — signal node (runs in parallel with the other
compute_* nodes after check_data_sufficiency).

Combines two considerations into one classification ('bullish' | 'neutral'
| 'bearish'):
  - implied upside/downside: (avg_price_target - current_price) / current_price,
    thresholded by ANALYST_UPSIDE_THRESHOLD_PCT
  - rating-revision trend: net upgrades minus downgrades within the
    trailing window fetch_fundamentals_data already applies (see
    RATING_CHANGE_WINDOW_DAYS in fetch_fundamentals_data.py) -- 'maintain'
    and 'initiate' actions aren't revisions, so they're excluded from the
    trend score but still reported in `detail` for transparency.

Returns classification=None with a "no analyst coverage" reason when
`analyst_data["price_target"]` is missing or carries zero analysts (see
the NOCOV sample ticker in backend/db/seed_fundamentals.py).
"""

from ..config import ANALYST_UPSIDE_THRESHOLD_PCT


def compute_analyst_consensus(state):
    analyst_data = state.get("analyst_data") or {}
    price_target = analyst_data.get("price_target")
    current_price = state.get("current_price")

    has_coverage = (
        price_target is not None
        and price_target.get("avg_price_target") is not None
        and (price_target.get("num_analysts") or 0) > 0
    )

    if not has_coverage:
        return {
            "analyst_consensus": {
                "classification": None,
                "detail": {"reason": "no analyst coverage"},
            }
        }

    if current_price is None:
        return {
            "analyst_consensus": {
                "classification": None,
                "detail": {"reason": "current_price not available"},
            }
        }

    avg_price_target = price_target["avg_price_target"]
    upside_pct = (avg_price_target - current_price) / current_price * 100
    price_target_signal = _sign(upside_pct, ANALYST_UPSIDE_THRESHOLD_PCT)

    rating_changes = analyst_data.get("rating_changes") or []
    upgrade_count = sum(1 for change in rating_changes if change.get("action") == "upgrade")
    downgrade_count = sum(1 for change in rating_changes if change.get("action") == "downgrade")
    net_rating_score = upgrade_count - downgrade_count
    rating_trend_signal = _sign(net_rating_score, 1)

    combined = price_target_signal + rating_trend_signal
    if combined > 0:
        classification = "bullish"
    elif combined < 0:
        classification = "bearish"
    else:
        classification = "neutral"

    detail = {
        "avg_price_target": round(avg_price_target, 2),
        "num_analysts": price_target.get("num_analysts"),
        "upside_pct": round(upside_pct, 2),
        "upgrade_count": upgrade_count,
        "downgrade_count": downgrade_count,
        "net_rating_score": net_rating_score,
        "rating_changes_considered": len(rating_changes),
    }

    return {"analyst_consensus": {"classification": classification, "detail": detail}}


def _sign(value, threshold):
    """Returns +1 if value >= threshold, -1 if value <= -threshold, else 0."""
    if value >= threshold:
        return 1
    if value <= -threshold:
        return -1
    return 0
