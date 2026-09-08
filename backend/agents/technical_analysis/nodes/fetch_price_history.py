"""fetch_price_history — data access node.

Pulls trailing daily OHLCV bars for `state["ticker"]` from Yahoo Finance via
`yfinance`. There is no database layer in this repo yet (see persist_results.py),
so unlike the Technical Analysis Subgraph specification's original design this
does not check a `universe` table or read from Postgres — an unknown ticker is
simply whatever yfinance returns nothing for.
"""

import datetime

import yfinance as yf

from ..config import LOOKBACK_DAYS, MIN_PRICE_HISTORY_ROWS

# Trading days are roughly 5/7 of calendar days, plus holidays; over-fetch by
# this factor (with a flat buffer) so `lookback_days` trading rows are
# actually available once we trim to the tail.
CALENDAR_DAYS_PER_TRADING_DAY = 1.6
CALENDAR_BUFFER_DAYS = 15


def _row_to_dict(index, row):
    close = float(row["Close"])
    volume = row["Volume"]
    return {
        "trade_date": index.date().isoformat(),
        "open_price": float(row["Open"]),
        "high_price": float(row["High"]),
        "low_price": float(row["Low"]),
        "close_price": close,
        "adjusted_close": close,
        "volume": int(volume) if volume == volume else None,  # NaN check
    }


def _fetch(ticker, lookback_days):
    """Returns None if yfinance has no data for the ticker at all."""
    calendar_days = int(lookback_days * CALENDAR_DAYS_PER_TRADING_DAY) + CALENDAR_BUFFER_DAYS
    start = datetime.date.today() - datetime.timedelta(days=calendar_days)

    data = yf.Ticker(ticker).history(start=start.isoformat())
    if data.empty:
        return None

    data = data.tail(lookback_days)
    return [_row_to_dict(index, row) for index, row in data.iterrows()]


def fetch_price_history(state):
    ticker = state.get("ticker")
    lookback_days = state.get("lookback_days") or LOOKBACK_DAYS

    try:
        result = _fetch(ticker, lookback_days)
    except Exception as exc:
        return {"fetch_failed": True, "fetch_error": f"failed to fetch price history for {ticker!r}: {exc}"}

    if result is None:
        return {"fetch_failed": True, "fetch_error": f"no price history found for ticker {ticker!r}"}

    if len(result) < MIN_PRICE_HISTORY_ROWS:
        return {
            "fetch_failed": True,
            "fetch_error": (
                f"insufficient price history for {ticker!r}: got {len(result)} row(s), "
                f"need at least {MIN_PRICE_HISTORY_ROWS}"
            ),
        }

    return {
        "fetch_failed": False,
        "fetch_error": None,
        "as_of_date": datetime.date.today().isoformat(),
        "price_history": result,
    }
