"""Shared state object threaded through every node in the graph.

Field ownership mirrors the "Reads" / "Writes" columns in
docs/fundamental-analysis-design.md Section 3.2.
"""

from typing import Optional, TypedDict


class FundamentalAnalysisState(TypedDict, total=False):
    # --- request input ---
    ticker: str
    ratio_basis: str  # 'TTM' | 'MRQ'
    lookback_years: int
    current_price: Optional[float]

    # --- validate_input ---
    is_valid: bool
    validation_error: Optional[str]

    # --- fetch_fundamentals_data ---
    fetch_failed: bool
    fetch_error: Optional[str]
    fundamentals_history: list
    analyst_data: dict
    as_of_date: Optional[str]
    sector: Optional[str]
    company_name: Optional[str]

    # --- check_data_sufficiency ---
    data_tier: Optional[str]  # 'full' | 'medium' | 'limited' | 'insufficient'

    # --- compute_* signal nodes (each: {"classification": str | None, "detail": dict}) ---
    relative_valuation: dict
    growth: dict
    financial_health: dict
    analyst_consensus: dict

    # --- aggregate_composite_signal ---
    composite_result: dict

    # --- terminal nodes ---
    error: Optional[dict]
    final_output: Optional[dict]