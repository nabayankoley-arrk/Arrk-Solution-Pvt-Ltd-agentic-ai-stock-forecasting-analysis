"""fetch_fundamentals_data — data access node.

Queries `universe`, `financial_statements`, `analyst_price_targets`, and
`analyst_rating_changes` (see backend/db/schema.sql) for `state["ticker"]`.
Retries transient connection failures before giving up. See
docs/fundamental-analysis-design.md Section 3.2, row
`fetch_fundamentals_data`.

Note: `current_price` is left untouched here. The specification calls for
fetching "current market data (if not supplied by Orchestrator)", but no
day-level price table is defined in this subgraph's schema — see the note
in backend/db/seed_fundamentals.py. Until a shared `prices` table exists
(likely owned by the Technical Analysis subgraph), `current_price` must
come from the Orchestrator's request payload.
"""

import datetime
import time
from decimal import Decimal

import psycopg2

from db.connection import get_connection

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 0.5

# Trailing quarters fetched regardless of lookback_years: enough for a
# TTM sum (4 quarters) plus the same quarter one year prior for YoY
# comparisons, with some slack for late/missing filings.
TRAILING_QUARTERS = 8

# Rating-change events older than this aren't useful for the "recent
# upgrade/downgrade trend" read in compute_analyst_consensus.
RATING_CHANGE_WINDOW_DAYS = 180

STATEMENT_COLUMNS = [
    "period_end_date", "period_type", "revenue", "gross_profit", "operating_profit",
    "net_profit", "eps", "total_debt", "total_equity", "cash_flow_operations",
    "inventory", "receivables", "shares_outstanding",
]

STATEMENT_SELECT = f"""
    SELECT {", ".join(STATEMENT_COLUMNS)}
    FROM financial_statements
    WHERE ticker = %s AND period_type = %s
"""


def _years_ago(today, years):
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        # today is Feb 29 and the target year has no Feb 29.
        return today.replace(month=2, day=28, year=today.year - years)


def _row_to_dict(row):
    record = dict(zip(STATEMENT_COLUMNS, row))
    record["period_end_date"] = record["period_end_date"].isoformat()
    for key, value in record.items():
        if isinstance(value, Decimal):
            record[key] = float(value)
    return record


def _fetch(ticker, lookback_years):
    """Runs all queries for one fetch attempt. Returns None if the ticker
    is not in `universe` (a real miss, not a transient failure)."""
    today = datetime.date.today()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT sector, company_name FROM universe WHERE ticker = %s", (ticker,))
            universe_row = cur.fetchone()
            if universe_row is None:
                return None
            sector, company_name = universe_row

            cur.execute(
                STATEMENT_SELECT + " AND period_end_date >= %s ORDER BY period_end_date ASC",
                (ticker, "annual", _years_ago(today, lookback_years)),
            )
            annual_rows = cur.fetchall()

            cur.execute(
                STATEMENT_SELECT + " ORDER BY period_end_date DESC LIMIT %s",
                (ticker, "quarterly", TRAILING_QUARTERS),
            )
            quarterly_rows = list(reversed(cur.fetchall()))

            cur.execute(
                """
                SELECT as_of_date, avg_price_target, num_analysts
                FROM analyst_price_targets
                WHERE ticker = %s
                ORDER BY as_of_date DESC
                LIMIT 1
                """,
                (ticker,),
            )
            price_target_row = cur.fetchone()

            cur.execute(
                """
                SELECT action_date, analyst_firm, action, from_rating, to_rating
                FROM analyst_rating_changes
                WHERE ticker = %s AND action_date >= %s
                ORDER BY action_date ASC
                """,
                (ticker, today - datetime.timedelta(days=RATING_CHANGE_WINDOW_DAYS)),
            )
            rating_change_rows = cur.fetchall()
    finally:
        conn.close()

    fundamentals_history = [_row_to_dict(row) for row in list(annual_rows) + quarterly_rows]

    price_target = None
    if price_target_row is not None:
        as_of_date, avg_price_target, num_analysts = price_target_row
        price_target = {
            "as_of_date": as_of_date.isoformat(),
            "avg_price_target": float(avg_price_target) if avg_price_target is not None else None,
            "num_analysts": num_analysts,
        }

    rating_changes = [
        {
            "action_date": action_date.isoformat(),
            "analyst_firm": analyst_firm,
            "action": action,
            "from_rating": from_rating,
            "to_rating": to_rating,
        }
        for action_date, analyst_firm, action, from_rating, to_rating in rating_change_rows
    ]

    return {
        "sector": sector,
        "company_name": company_name,
        "fundamentals_history": fundamentals_history,
        "analyst_data": {"price_target": price_target, "rating_changes": rating_changes},
    }


def fetch_fundamentals_data(state):
    ticker = state.get("ticker")
    lookback_years = state.get("lookback_years") or 5

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = _fetch(ticker, lookback_years)
            break
        except psycopg2.OperationalError as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)
    else:
        return {"fetch_failed": True, "fetch_error": f"database connection failed: {last_error}"}

    if result is None:
        return {"fetch_failed": True, "fetch_error": f"ticker {ticker!r} not found in universe"}

    return {
        "fetch_failed": False,
        "fetch_error": None,
        "as_of_date": datetime.date.today().isoformat(),
        **result,
    }
