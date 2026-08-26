"""Shared indicator math for the compute_* nodes.

Not a node itself -- pure functions over plain lists of floats (no
pandas/numpy dependency, matching this project's existing preference for
raw psycopg2 rows over a dataframe layer -- see backend/db/upsert.py).
Every function returns None (rather than raising) when there isn't enough
history to compute a value, so callers can degrade gracefully instead of
crashing on a ticker with a short price history.
"""


def sma(values, period):
    """Simple moving average of the trailing `period` values."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values, period):
    """Exponential moving average, seeded with an SMA, over the full
    series. Returns a list the same length as `values`; entries before
    the seed point are None.
    """
    n = len(values)
    result = [None] * n
    if n < period:
        return result

    multiplier = 2 / (period + 1)
    seed = sum(values[:period]) / period
    result[period - 1] = seed

    prev = seed
    for i in range(period, n):
        prev = (values[i] - prev) * multiplier + prev
        result[i] = prev
    return result


def rsi(closes, period):
    """Wilder's RSI. Returns None if there's less than `period + 1` closes."""
    n = len(closes)
    if n < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(closes, fast, slow, signal):
    """Returns {"macd_line", "signal_line", "histogram"} (latest values
    only), or all-None values if there isn't enough history for the slow
    EMA plus the signal EMA on top of it.
    """
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)

    macd_values = [
        f - s for f, s in zip(ema_fast, ema_slow) if f is not None and s is not None
    ]
    if len(macd_values) < signal:
        return {"macd_line": None, "signal_line": None, "histogram": None}

    signal_series = ema_series(macd_values, signal)
    latest_macd = macd_values[-1]
    latest_signal = signal_series[-1]
    histogram = None if latest_signal is None else latest_macd - latest_signal

    return {"macd_line": latest_macd, "signal_line": latest_signal, "histogram": histogram}


def atr(highs, lows, closes, period):
    """Wilder's Average True Range. Returns None without `period + 1` bars."""
    n = len(closes)
    if n < period + 1:
        return None

    true_ranges = []
    for i in range(1, n):
        true_ranges.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )

    value = sum(true_ranges[:period]) / period
    for i in range(period, len(true_ranges)):
        value = (value * (period - 1) + true_ranges[i]) / period
    return value


def bollinger_bands(closes, period, std_dev):
    """Returns {"middle", "upper", "lower", "width_pct"}, or None without
    `period` closes. `width_pct` is (upper - lower) / middle * 100.
    """
    if len(closes) < period:
        return None

    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((c - middle) ** 2 for c in window) / period
    std = variance ** 0.5

    upper = middle + std_dev * std
    lower = middle - std_dev * std
    width_pct = (upper - lower) / middle * 100 if middle else None

    return {"middle": middle, "upper": upper, "lower": lower, "width_pct": width_pct}
