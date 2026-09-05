"""Resolves a ticker's latest close price directly from the Technical
Analysis Agent's own price_history table, without running that agent's
full subgraph.

fetch_fundamental_analysis and fetch_technical_analysis run independently
and in parallel (see the Orchestrator Subgraph specification's
Architecture section: "the three baseline passes are independent and can
execute in parallel"), so fundamental analysis can no longer wait for a
completed technical_analysis result to derive current_price the way the
previous linear sketch did. Both pillars now read the same underlying
table independently instead.
"""

import psycopg2

from db.connection import get_connection


def get_current_price(ticker):
    """Returns (current_price, error). error is None on success; on any
    failure current_price is None and error explains why. Callers should
    degrade gracefully (see _pillar_runners.run_fundamental) rather than
    treat this as fatal to the whole fundamental pillar -- Fundamental
    Analysis's own compute_relative_valuation already handles a missing
    current_price as an "insufficient data" signal, not a hard error.
    """
    try:
        conn = get_connection()
    except psycopg2.OperationalError as exc:
        return None, f"database connection failed: {exc}"

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT close_price FROM "Technical".price_history
                WHERE ticker = %s
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (ticker,),
            )
            row = cur.fetchone()
    except psycopg2.Error as exc:
        return None, f"price_history query failed: {exc}"
    finally:
        conn.close()

    if row is None:
        return None, f"no price history found for ticker {ticker!r}"
    return float(row[0]), None
