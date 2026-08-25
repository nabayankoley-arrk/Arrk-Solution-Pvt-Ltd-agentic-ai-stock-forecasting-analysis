"""check_data_sufficiency — guard node.

Counts distinct annual reporting years in `fundamentals_history` and
assigns a `data_tier`. Boundary semantics (e.g. whether exactly 2 years
lands in 'limited' or 'medium') follow the config thresholds below; confirm
against the full specification before relying on the edges. See
docs/fundamental-analysis-design.md Section 3.2, row
`check_data_sufficiency`, and Section 5 for the threshold defaults.
"""

from ..config import FULL_TIER_YEARS, LIMITED_TIER_YEARS, MIN_FILING_YEARS


def check_data_sufficiency(state):
    history = state.get("fundamentals_history") or []
    annual_years = {row["period_end_date"] for row in history if row.get("period_type") == "annual"}
    year_count = len(annual_years)

    if year_count < MIN_FILING_YEARS:
        data_tier = "insufficient"
    elif year_count < LIMITED_TIER_YEARS:
        data_tier = "limited"
    elif year_count < FULL_TIER_YEARS:
        data_tier = "medium"
    else:
        data_tier = "full"

    return {"data_tier": data_tier}
