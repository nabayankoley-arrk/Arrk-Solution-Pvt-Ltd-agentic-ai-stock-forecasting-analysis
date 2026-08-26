"""compute_relative_valuation — signal node (runs in parallel with the
other compute_* nodes after check_data_sufficiency).

Computes P/E, P/B, and PEG from `fundamentals_history` and `current_price`,
classifying as 'cheap' | 'fair' | 'expensive' using VALUATION_BAND_PCT
around a PEG of 1.0.

Limitation: the source specification calls for comparing against "the
ticker's own historical average", which implies a historical *stock
price* series. This schema has no price-history table -- day-level prices
are explicitly out of scope here, owned by the (not yet built) Technical
Analysis subgraph (see the notes in backend/db/seed_fundamentals.py and
fetch_fundamentals_data.py). Classification therefore uses PEG (P/E
weighed against the company's own EPS growth) instead of a historical
price baseline -- still a genuine, standard relative-valuation measure,
just not "relative to its own trading history" as originally phrased.
"""

from ..config import VALUATION_BAND_PCT
from ._financial_helpers import current_flow_figures, latest_annual, pct_change, prior_annual, safe_div


def compute_relative_valuation(state):
    history = state.get("fundamentals_history") or []
    current_price = state.get("current_price")
    ratio_basis = state.get("ratio_basis", "TTM")

    latest = latest_annual(history)
    prior = prior_annual(history)
    current = current_flow_figures(history, ratio_basis)

    if latest is None or current is None or current_price is None:
        return {
            "relative_valuation": {
                "classification": None,
                "detail": {"reason": "insufficient data: requires at least one annual period and current_price"},
            }
        }

    eps = current.get("eps")
    pe_ratio = safe_div(current_price, eps) if eps and eps > 0 else None

    book_value_per_share = safe_div(latest.get("total_equity"), latest.get("shares_outstanding"))
    pb_ratio = safe_div(current_price, book_value_per_share)

    eps_growth_pct = pct_change(latest.get("eps"), prior.get("eps")) if prior else None
    peg_ratio = None
    if pe_ratio is not None and eps_growth_pct is not None and eps_growth_pct > 0:
        peg_ratio = pe_ratio / eps_growth_pct

    band = VALUATION_BAND_PCT / 100
    reason = None
    if peg_ratio is None:
        classification = None
        reason = "PEG not computable (requires positive EPS, a prior annual period, and positive EPS growth)"
    elif peg_ratio < 1 - band:
        classification = "cheap"
    elif peg_ratio > 1 + band:
        classification = "expensive"
    else:
        classification = "fair"

    detail = {
        "pe_ratio": _round(pe_ratio),
        "pb_ratio": _round(pb_ratio),
        "peg_ratio": _round(peg_ratio),
        "eps_growth_pct_used_for_peg": _round(eps_growth_pct),
        "note": (
            "classification uses PEG (P/E vs. the company's own EPS growth), not a historical-price "
            "baseline -- this schema has no historical price table for the ticker's own trading history"
        ),
    }
    if reason:
        detail["reason"] = reason

    return {"relative_valuation": {"classification": classification, "detail": detail}}


def _round(value):
    return round(value, 2) if value is not None else None
