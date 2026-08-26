"""Shared helpers for the compute_* signal nodes.

Not a node itself -- imported by compute_growth, compute_relative_valuation,
and compute_financial_health to avoid duplicating the same period-selection,
safe-division, and TTM-summing logic three times. Operates on
`fundamentals_history` (see state.py), a flat list of rows mixing annual
and quarterly periods as returned by fetch_fundamentals_data.
"""


def annual_periods(history):
    """Returns annual rows from `fundamentals_history`, oldest first."""
    rows = [row for row in history if row.get("period_type") == "annual"]
    return sorted(rows, key=lambda row: row["period_end_date"])


def quarterly_periods(history):
    """Returns quarterly rows from `fundamentals_history`, oldest first."""
    rows = [row for row in history if row.get("period_type") == "quarterly"]
    return sorted(rows, key=lambda row: row["period_end_date"])


def latest_annual(history):
    """Returns the most recent annual row, or None if there isn't one."""
    annual = annual_periods(history)
    return annual[-1] if annual else None


def prior_annual(history):
    """Returns the second-most-recent annual row, or None."""
    annual = annual_periods(history)
    return annual[-2] if len(annual) >= 2 else None


def safe_div(numerator, denominator):
    """Returns numerator / denominator, or None if either operand is
    missing or the denominator is zero -- financial figures are
    frequently null (e.g. NOCOV's null inventory in seed_fundamentals.py),
    and a missing/zero denominator should degrade a check to
    "unavailable", not crash the whole node.
    """
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def pct_change(current, previous):
    """Returns the percentage change from `previous` to `current`, or
    None if either is missing or `previous` is zero.
    """
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous * 100


def ttm_flow_figures(history):
    """Sums revenue/net_profit/eps/cash_flow_operations over the trailing
    4 quarterly rows. Returns None if fewer than 4 quarters exist, or if
    any of the trailing 4 rows has a null value for a given field (a
    partial sum would misrepresent TTM).
    """
    quarters = quarterly_periods(history)
    if len(quarters) < 4:
        return None

    trailing = quarters[-4:]

    def _sum(field):
        values = [row.get(field) for row in trailing]
        return None if any(value is None for value in values) else sum(values)

    return {
        "revenue": _sum("revenue"),
        "net_profit": _sum("net_profit"),
        "eps": _sum("eps"),
        "cash_flow_operations": _sum("cash_flow_operations"),
    }


def current_flow_figures(history, ratio_basis):
    """Returns {revenue, net_profit, eps, cash_flow_operations} on the
    basis `ratio_basis` requests.

    'TTM' sums the trailing 4 quarters when available; otherwise (and
    always for 'MRQ', since annualizing a single quarter isn't specified
    in the source document) this falls back to the most recent annual
    period's full-year figures. Balance-sheet figures (debt, equity,
    inventory, receivables, shares outstanding) are always point-in-time,
    not flow figures -- read those directly from latest_annual() instead.
    """
    latest = latest_annual(history)
    if latest is None:
        return None

    fallback = {
        "revenue": latest.get("revenue"),
        "net_profit": latest.get("net_profit"),
        "eps": latest.get("eps"),
        "cash_flow_operations": latest.get("cash_flow_operations"),
    }

    if ratio_basis == "TTM":
        ttm = ttm_flow_figures(history)
        if ttm is not None:
            return ttm

    return fallback
