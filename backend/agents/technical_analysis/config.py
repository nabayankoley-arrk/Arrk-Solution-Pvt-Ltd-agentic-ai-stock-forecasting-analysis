"""Tunable constants for the Technical Analysis Agent.

Names and values in the first block come directly from the "Technical
Specifications" section of the Technical Analysis Subgraph specification.
The second block covers thresholds the specification describes in words
("configurable thresholds", "sufficient market participation") but does
not give a concrete default for -- each is flagged with a comment; revisit
once real price history is available to tune against.
"""

# --- fetch_price_history / compute_trend ---
LOOKBACK_DAYS = 250
SHORT_MA_PERIOD = 20
MEDIUM_MA_PERIOD = 50
LONG_MA_PERIOD = 200

# --- compute_momentum ---
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# --- compute_volatility ---
ATR_PERIOD = 14
BOLLINGER_PERIOD = 20
BOLLINGER_STD_DEV = 2

# --- compute_support_resistance ---
# Specification gives a 20-60 day range for this window; fixed at the
# midpoint here as a single configurable default.
SUPPLY_DEMAND_WINDOW = 40

# --- check_volume_confirmation ---
VOLUME_LOOKBACK = 10

# --- calculate_rrr ---
MIN_RRR = 1.5

# --- derive_stoploss_and_target ---
SR_TOLERANCE_PERCENT = 4

# --- detect_candlestick_pattern ---
SHADOW_TOLERANCE_PERCENT = 8

# ---------------------------------------------------------------------
# Thresholds referenced by the specification's prose but with no numeric
# default given there -- chosen as a reasonable starting point.
# ---------------------------------------------------------------------

# --- compute_momentum: RSI overbought/oversold bands ---
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# --- compute_volatility: ATR as a percentage of price ---
ATR_PERCENT_LOW_THRESHOLD = 1.5
ATR_PERCENT_HIGH_THRESHOLD = 3.5

# --- compute_support_resistance: swing high/low detection ---
# A candle is a swing high/low if it is the most extreme high/low among
# itself and this many candles on each side.
SWING_ARM_LENGTH = 2

# --- aggregate_technical_signal ---
TREND_WEIGHT = 0.6
MOMENTUM_WEIGHT = 0.4
AGGREGATE_NEUTRAL_BAND = 0.15
# Volatility doesn't get a vote in direction, but discounts confidence --
# a "High" volatility read makes any directional signal less reliable.
VOLATILITY_CONFIDENCE_MULTIPLIER = {"low": 1.0, "medium": 0.9, "high": 0.7}

# --- check_volume_confirmation ---
# Latest volume must be at least this multiple of the trailing average to
# count as confirming a candlestick pattern.
VOLUME_CONFIRMATION_RATIO = 1.2

# --- fetch_price_history ---
# Below this many rows, moving averages/RSI/MACD/ATR are too unreliable
# to classify anything meaningfully; treated as a fetch failure rather
# than a silent all-None result.
MIN_PRICE_HISTORY_ROWS = SHORT_MA_PERIOD
