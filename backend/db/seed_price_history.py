"""seed_price_history — populates "Technical".price_history with REAL OHLCV
bars fetched live from yfinance, the counterpart to seed_fundamentals.py.

Nothing else in this repo writes that table: db/upsert.py's
save_price_history() has existed without a caller, and the
backend/ingestion/yfinance_price_history_demo.py that
agents/technical_analysis/smoke_test.py points at has never existed. Two
things depend on the table being populated:

  - agents/technical_analysis/nodes/fetch_price_history.py reads the bars
    every indicator is computed from. Below config.MIN_PRICE_HISTORY_ROWS
    (20) it treats the fetch as failed outright, and the 200-period moving
    average in compute_trend needs far more than that to mean anything.
  - agents/orchestrator/nodes/_current_price.py takes the latest close as
    Fundamental Analysis's `current_price`, without which that agent's
    compute_relative_valuation and compute_analyst_consensus both report
    "insufficient data" no matter how complete the filings are.

Seeds every ticker in `universe` by default, or only those named on the
command line. A ticker must already be in `universe` -- price_history has
a foreign key to it, and nothing in this repo populates `universe` itself
(same constraint as seed_fundamentals.py; see README.md).

Run from the backend/ directory, as a module so the relative import below
resolves:

    python -m db.seed_price_history                # every ticker in universe
    python -m db.seed_price_history TCS.NS INFY.NS # just these

DEFAULT_PERIOD is 3y rather than the 250 trading days config.LOOKBACK_DAYS
asks for: the Orchestrator's long_term horizon requests lookback_days=500
(see agents/orchestrator/config.py's HORIZON_TO_PILLAR_PARAMS), which is
about two calendar years of trading days, and a margin on top costs one
request either way. Yahoo rate-limits aggressively from shared egress IPs
-- a "Too Many Requests" failure here is transient, so just re-run.
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import math
import sys

import yfinance as yf

from .connection import get_connection
from .upsert import save_price_history

DEFAULT_PERIOD = "3y"

# yfinance column -> the key fetch_price_history.py/save_price_history use.
_COLUMN_MAP = {
    "Open": "open_price",
    "High": "high_price",
    "Low": "low_price",
    "Close": "close_price",
    "Adj Close": "adjusted_close",
    "Volume": "volume",
}


def _clean_float(value):
    """NaN/None/non-numeric -> None, so a gap in Yahoo's data is stored as
    NULL rather than as the float nan psycopg2 would otherwise send."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _clean_int(value):
    number = _clean_float(value)
    return None if number is None else int(number)


def _build_rows(frame):
    """One dict per trading day, in the shape save_price_history expects.

    auto_adjust=False is requested below so the frame keeps `Close` and
    `Adj Close` as separate columns -- yfinance defaults auto_adjust=True,
    which overwrites Close with the adjusted series and drops Adj Close
    entirely, leaving nothing to put in adjusted_close. Older/partial
    responses may still omit it, so it falls back to Close rather than
    failing the whole ticker.
    """
    rows = []
    for timestamp, record in frame.iterrows():
        row = {"trade_date": timestamp.date()}
        for source, key in _COLUMN_MAP.items():
            value = record.get(source)
            row[key] = _clean_int(value) if key == "volume" else _clean_float(value)

        if row["adjusted_close"] is None:
            row["adjusted_close"] = row["close_price"]

        # A day with no close is unusable -- every indicator is derived from
        # it -- so drop the bar rather than storing a NULL-close row that
        # compute_trend would have to defend against.
        if row["close_price"] is None:
            continue
        rows.append(row)
    return rows


def seed_ticker(ticker, period=DEFAULT_PERIOD):
    """Fetches and upserts one ticker's bars. Returns (row_count, first_date,
    last_date); row_count is 0 when Yahoo returned nothing usable."""
    frame = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    if frame is None or frame.empty:
        return 0, None, None

    rows = _build_rows(frame)
    save_price_history(ticker, rows)
    if not rows:
        return 0, None, None
    return len(rows), rows[0]["trade_date"], rows[-1]["trade_date"]


def main(argv=None):
    requested = [ticker.strip().upper() for ticker in (argv or []) if ticker.strip()]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ticker FROM universe ORDER BY ticker")
        known = [row[0] for row in cur.fetchall()]

    if requested:
        unknown = [ticker for ticker in requested if ticker not in known]
        for ticker in unknown:
            print(f"{ticker}: SKIPPED -- not in universe (insert it there first; see README.md)")
        tickers = [ticker for ticker in requested if ticker in known]
    else:
        tickers = known

    if not tickers:
        # Distinguish the two ways of ending up with nothing to do: an empty
        # `universe`, versus every named ticker missing from a populated one.
        if requested:
            print("nothing to seed: none of the named tickers are in universe")
        else:
            print("nothing to seed: universe is empty (see README.md)")
        return

    for ticker in tickers:
        try:
            count, first_date, last_date = seed_ticker(ticker)
            if count:
                print(f"{ticker}: seeded {count} price_history rows ({first_date} to {last_date})")
            else:
                print(f"{ticker}: no price data returned")
        except Exception as exc:
            print(f"{ticker}: FAILED -- {exc}")


if __name__ == "__main__":
    main(sys.argv[1:])
