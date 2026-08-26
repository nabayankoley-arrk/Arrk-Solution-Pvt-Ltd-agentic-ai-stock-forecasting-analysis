"""compute_growth — signal node (runs in parallel with the other compute_*
nodes after check_data_sufficiency).

Classifies YoY revenue growth as 'accelerating' | 'stable' | 'decelerating'
by comparing the latest YoY growth rate to the prior year's YoY growth
rate, using GROWTH_TREND_DELTA_PCT as the acceleration/deceleration
threshold. Also flags EPS dilution (net profit growing faster than EPS,
via EPS_DILUTION_GAP_PCT) and revenue/profit sign misalignment.

Segment breakdown (mentioned in docs/fundamental-analysis-design.md
Section 3.2) is not implemented: `fundamentals_history` carries no
segment-level fields in this schema (see backend/db/schema.sql), so
`detail["segment_breakdown"]` is always None.
"""

from ..config import EPS_DILUTION_GAP_PCT, GROWTH_TREND_DELTA_PCT
from ._financial_helpers import annual_periods, pct_change


def compute_growth(state):
    history = state.get("fundamentals_history") or []
    annual = annual_periods(history)

    if len(annual) < 2:
        return {
            "growth": {
                "classification": None,
                "detail": {"reason": "fewer than 2 annual periods available"},
            }
        }

    latest, prior = annual[-1], annual[-2]

    revenue_growth_pct = pct_change(latest.get("revenue"), prior.get("revenue"))
    net_profit_growth_pct = pct_change(latest.get("net_profit"), prior.get("net_profit"))
    eps_growth_pct = pct_change(latest.get("eps"), prior.get("eps"))

    if revenue_growth_pct is None:
        return {
            "growth": {
                "classification": None,
                "detail": {
                    "reason": "revenue growth not computable (missing or zero prior-period revenue)",
                    "net_profit_growth_pct": _round(net_profit_growth_pct),
                    "eps_growth_pct": _round(eps_growth_pct),
                },
            }
        }

    dilution_flag = (
        net_profit_growth_pct is not None
        and eps_growth_pct is not None
        and (net_profit_growth_pct - eps_growth_pct) > EPS_DILUTION_GAP_PCT
    )

    revenue_profit_misaligned = (
        net_profit_growth_pct is not None
        and (revenue_growth_pct > 0) != (net_profit_growth_pct > 0)
    )

    classification = "stable"
    prior_revenue_growth_pct = None
    trend_reason = None
    if len(annual) >= 3:
        older = annual[-3]
        prior_revenue_growth_pct = pct_change(prior.get("revenue"), older.get("revenue"))
        if prior_revenue_growth_pct is not None:
            delta = revenue_growth_pct - prior_revenue_growth_pct
            if delta > GROWTH_TREND_DELTA_PCT:
                classification = "accelerating"
            elif delta < -GROWTH_TREND_DELTA_PCT:
                classification = "decelerating"
            else:
                classification = "stable"
        else:
            trend_reason = "prior-year growth rate not computable; defaulting to 'stable'"
    else:
        trend_reason = "fewer than 3 annual periods available; cannot assess trend, defaulting to 'stable'"

    detail = {
        "revenue_growth_pct": _round(revenue_growth_pct),
        "net_profit_growth_pct": _round(net_profit_growth_pct),
        "eps_growth_pct": _round(eps_growth_pct),
        "prior_revenue_growth_pct": _round(prior_revenue_growth_pct),
        "dilution_flag": dilution_flag,
        "revenue_profit_misaligned": revenue_profit_misaligned,
        "segment_breakdown": None,
    }
    if trend_reason:
        detail["reason"] = trend_reason

    return {"growth": {"classification": classification, "detail": detail}}


def _round(value):
    return round(value, 2) if value is not None else None
