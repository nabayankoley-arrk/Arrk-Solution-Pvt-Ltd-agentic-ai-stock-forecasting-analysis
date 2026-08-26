"""compute_financial_health — signal node (runs in parallel with the other
compute_* nodes after check_data_sufficiency).

Runs six pass/fail checks against the latest annual period -- gross
margin (GPM_THRESHOLD_PCT), debt-to-equity (DEBT_TO_EQUITY_THRESHOLD),
ROE (ROE_THRESHOLD_PCT), cash-flow quality (MIN_CFO_TO_NET_PROFIT_RATIO),
receivables quality, and inventory efficiency (both using
RECEIVABLES_GROWTH_GAP_PCT, and both requiring a prior annual period to
compute a YoY growth rate) -- and classifies 'strong' (all applicable
checks pass), 'weak' (half or fewer pass), or 'stable' (otherwise).

Inventory efficiency is skipped (not counted toward the total) when
`state["sector"]` is a sector that doesn't carry inventory (e.g.
Services -- see NOCOV in backend/db/seed_fundamentals.py) or when the
latest period's inventory is null, per the sector-gating called for in
docs/fundamental-analysis-design.md Section 3.2.

DEBT_TO_EQUITY_THRESHOLD is a flat threshold, not sector-banded --
config.py flags the sector-dependent bands (1.0-1.5x per the design doc)
as an open question still requiring product input.
"""

from ..config import (
    DEBT_TO_EQUITY_THRESHOLD,
    GPM_THRESHOLD_PCT,
    MIN_CFO_TO_NET_PROFIT_RATIO,
    RECEIVABLES_GROWTH_GAP_PCT,
    ROE_THRESHOLD_PCT,
)
from ._financial_helpers import annual_periods, pct_change, safe_div

# Sectors known not to carry inventory, matching the NOCOV (Services) sample
# ticker in seed_fundamentals.py, whose inventory column is always null.
SECTORS_WITHOUT_INVENTORY = {"Services"}


def compute_financial_health(state):
    history = state.get("fundamentals_history") or []
    sector = state.get("sector")
    annual = annual_periods(history)

    if not annual:
        return {
            "financial_health": {
                "classification": None,
                "detail": {"reason": "no annual periods available"},
            }
        }

    latest = annual[-1]
    prior = annual[-2] if len(annual) >= 2 else None

    checks = {}

    gpm_ratio = safe_div(latest.get("gross_profit"), latest.get("revenue"))
    gpm_pct = gpm_ratio * 100 if gpm_ratio is not None else None
    if gpm_pct is not None:
        checks["gross_margin"] = gpm_pct >= GPM_THRESHOLD_PCT

    debt_to_equity = safe_div(latest.get("total_debt"), latest.get("total_equity"))
    if debt_to_equity is not None:
        checks["debt_to_equity"] = debt_to_equity <= DEBT_TO_EQUITY_THRESHOLD

    roe_ratio = safe_div(latest.get("net_profit"), latest.get("total_equity"))
    roe_pct = roe_ratio * 100 if roe_ratio is not None else None
    if roe_pct is not None:
        checks["roe"] = roe_pct >= ROE_THRESHOLD_PCT

    cfo_to_net_profit = safe_div(latest.get("cash_flow_operations"), latest.get("net_profit"))
    if cfo_to_net_profit is not None:
        checks["cash_flow_quality"] = cfo_to_net_profit >= MIN_CFO_TO_NET_PROFIT_RATIO

    revenue_growth_pct = pct_change(latest.get("revenue"), prior.get("revenue")) if prior else None

    receivables_growth_pct = pct_change(latest.get("receivables"), prior.get("receivables")) if prior else None
    if revenue_growth_pct is not None and receivables_growth_pct is not None:
        checks["receivables_quality"] = (receivables_growth_pct - revenue_growth_pct) <= RECEIVABLES_GROWTH_GAP_PCT

    inventory_applicable = sector not in SECTORS_WITHOUT_INVENTORY and latest.get("inventory") is not None
    inventory_growth_pct = None
    if inventory_applicable and prior and prior.get("inventory") is not None:
        inventory_growth_pct = pct_change(latest.get("inventory"), prior.get("inventory"))
        if revenue_growth_pct is not None and inventory_growth_pct is not None:
            checks["inventory_efficiency"] = (inventory_growth_pct - revenue_growth_pct) <= RECEIVABLES_GROWTH_GAP_PCT

    if not checks:
        classification = None
        reason = "no individual checks were computable from available data"
    else:
        pass_count = sum(1 for passed in checks.values() if passed)
        total_count = len(checks)
        if pass_count == total_count:
            classification = "strong"
        elif pass_count <= total_count / 2:
            classification = "weak"
        else:
            classification = "stable"
        reason = None

    detail = {
        "gross_margin_pct": _round(gpm_pct),
        "debt_to_equity": _round(debt_to_equity),
        "roe_pct": _round(roe_pct),
        "cfo_to_net_profit": _round(cfo_to_net_profit),
        "revenue_growth_pct": _round(revenue_growth_pct),
        "receivables_growth_pct": _round(receivables_growth_pct),
        "inventory_growth_pct": _round(inventory_growth_pct),
        "inventory_check_applicable": inventory_applicable,
        "checks_passed": {name: bool(passed) for name, passed in checks.items()},
    }
    if reason:
        detail["reason"] = reason

    return {"financial_health": {"classification": classification, "detail": detail}}


def _round(value):
    return round(value, 2) if value is not None else None
