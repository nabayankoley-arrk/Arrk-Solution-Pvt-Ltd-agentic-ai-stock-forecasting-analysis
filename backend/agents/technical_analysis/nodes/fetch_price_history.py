"""fetch_price_history — data access node.

Queries `universe` and `price_history` (see the Technical Analysis
Subgraph specification's Database Schema section) for `state["ticker"]`.
Retries transient connection failures before giving up, matching
fetch_fundamentals_data.py's pattern in the Fundamental Analysis Agent.

Note: this reads a `universe.active` column. The Fundamental Analysis
Agent's `universe` table (backend/db/schema.sql) doesn't have one --
if that table is being reused here rather than recreated, run
`ALTER TABLE universe ADD COLUMN active BOOLEAN DEFAULT TRUE;` first.
"""

import datetime
import time

import psycopg2

from db.connection import get_connection

from ..config import LOOKBACK_DAYS, MIN_PRICE_HISTORY_ROWS

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 0.5

PRICE_COLUMNS = [
    "trade_date", "open_price", "high_price", "low_price",
    "close_price", "adjusted_close", "volume",
]

PRICE_HISTORY_SELECT = f"""
    SELECT {", ".join(PRICE_COLUMNS)}
    FROM "Technical".price_history
    WHERE ticker = %s
    ORDER BY trade_date DESC
    LIMIT %s
"""


def _row_to_dict(row):
    record = dict(zip(PRICE_COLUMNS, row))
    record["trade_date"] = record["trade_date"].isoformat()
    for key in ("open_price", "high_price", "low_price", "close_price", "adjusted_close"):
        if record[key] is not None:
            record[key] = float(record[key])
    return record


def _fetch(ticker, lookback_days):
    """Runs all queries for one fetch attempt. Returns None if the ticker
    is not in `universe` (a real miss, not a transient failure)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM universe WHERE ticker = %s AND active", (ticker,))
            if cur.fetchone() is None:
                return None

            cur.execute(PRICE_HISTORY_SELECT, (ticker, lookback_days))
            rows = list(reversed(cur.fetchall()))
    finally:
        conn.close()

    return [_row_to_dict(row) for row in rows]


def fetch_price_history(state):
    ticker = state.get("ticker")
    lookback_days = state.get("lookback_days") or LOOKBACK_DAYS

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = _fetch(ticker, lookback_days)
            break
        except psycopg2.OperationalError as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)
    else:
        return {"fetch_failed": True, "fetch_error": f"database connection failed: {last_error}"}

    if result is None:
        return {"fetch_failed": True, "fetch_error": f"ticker {ticker!r} not found in universe"}

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
