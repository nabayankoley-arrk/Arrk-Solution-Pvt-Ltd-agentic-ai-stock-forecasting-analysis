"""persist_results — terminal node.

Caches the price bars fetch_price_history.py just fetched from yfinance
into "Technical".price_history, so
agents/orchestrator/nodes/_current_price.py -- which reads only from that
table, not from yfinance -- can resolve a current price for Fundamental
Analysis. This is the only thing this node persists: there is no
Technical Analysis results table in this repo's confirmed schema (see
backend/db/schema.sql's note on that), so the aggregated signal/trade-setup
output itself still isn't cached anywhere.

Best-effort: if the database is unreachable, this silently skips caching
rather than failing the whole request -- the caller already has its
completed analysis in `final_output` regardless of whether this succeeds.
"""

import psycopg2

from db.upsert import save_price_history


def persist_results(state):
    price_history = state.get("price_history")
    ticker = state.get("ticker")
    if not price_history or not ticker:
        return {}

    try:
        save_price_history(ticker, price_history)
    except psycopg2.Error:
        pass
    return {}
