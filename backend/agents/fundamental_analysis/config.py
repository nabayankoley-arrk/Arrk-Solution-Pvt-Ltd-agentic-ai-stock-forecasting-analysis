"""Tunable constants for the Fundamental Analysis Agent.

Values and owning steps per docs/fundamental-analysis-design.md Section 5.
Two values have no concrete default in the source specification (flagged
below as TODO) and must be decided before compute_financial_health can be
considered complete — see the design doc's Section 6, item 3.
"""

VALID_RATIO_BASES = ("TTM", "MRQ")

# --- check_data_sufficiency ---
MIN_FILING_YEARS = 1
LIMITED_TIER_YEARS = 2
FULL_TIER_YEARS = 5

# --- compute_financial_health ---
GPM_THRESHOLD_PCT = 20
DEBT_TO_EQUITY_THRESHOLD = 1.25  # TODO: confirm sector-dependent bands (1.0-1.5x per design doc)
ROE_THRESHOLD_PCT = 25
MIN_CFO_TO_NET_PROFIT_RATIO = 0.8
# 15pp: no numeric default was given in the source specification. Chosen so it
# comfortably trips on the seeded DEMO 2023 scenario (receivables +42.9% vs.
# revenue +16.0%, a 26.9pp gap) while tolerating ordinary quarter-to-quarter
# noise. Revisit if real ingested data shows this threshold too tight/loose.
RECEIVABLES_GROWTH_GAP_PCT = 15

# --- compute_growth ---
EPS_DILUTION_GAP_PCT = 3
GROWTH_TREND_DELTA_PCT = 2

# --- compute_relative_valuation ---
VALUATION_BAND_PCT = 10

# --- compute_analyst_consensus ---
ANALYST_UPSIDE_THRESHOLD_PCT = 10

# --- aggregate_composite_signal ---
COMPOSITE_WEIGHTS = {
    "financial_health": 0.35,
    "relative_valuation": 0.25,
    "growth": 0.25,
    "analyst_consensus": 0.15,
}