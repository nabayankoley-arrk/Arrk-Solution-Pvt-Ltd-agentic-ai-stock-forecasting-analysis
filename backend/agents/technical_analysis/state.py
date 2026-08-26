"""Shared state object threaded through every node in the graph.

Field ownership mirrors the "Reads" / "Writes" of each node in the
Technical Analysis Subgraph specification's node descriptions.
"""

from typing import Optional, TypedDict


class TechnicalAnalysisState(TypedDict, total=False):
    # --- request input ---
    ticker: str
    lookback_days: int

    # --- validate_input ---
    is_valid: bool
    validation_error: Optional[str]

    # --- fetch_price_history ---
    fetch_failed: bool
    fetch_error: Optional[str]
    price_history: list
    as_of_date: Optional[str]

    # --- compute_trend / compute_momentum / compute_volatility /
    #     compute_support_resistance (each: {"classification": .., "detail": {...}}
    #     except support_resistance, which is {"support": .., "resistance": .., "detail": {...}}) ---
    trend: dict
    momentum: dict
    volatility: dict
    support_resistance: dict

    # --- aggregate_technical_signal ---
    technical_signal: dict
    confidence: Optional[float]

    # --- detect_candlestick_pattern ---
    candlestick_pattern: Optional[dict]  # {"name": str, "low": float, "high": float} | None
    pattern_direction: Optional[str]  # 'bullish' | 'bearish' | None

    # --- check_prior_trend_alignment / check_volume_confirmation
    #     (each: {"passed": bool, "reason": str | None, ...}) ---
    prior_trend_ok: dict
    volume_ok: dict

    # --- derive_stoploss_and_target / calculate_rrr ---
    entry_price: Optional[float]
    stop_loss: Optional[float]
    target: Optional[float]
    rrr: Optional[float]
    trade_setup: Optional[dict]

    # --- terminal nodes ---
    error: Optional[dict]
    final_output: Optional[dict]
