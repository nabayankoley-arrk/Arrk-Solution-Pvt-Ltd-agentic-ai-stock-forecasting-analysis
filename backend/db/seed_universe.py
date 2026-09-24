"""seed_universe — populates `universe` with the top 20 BSE-listed companies
by market capitalisation (jobs.top20), the FK parent every other table in
this project needs a row in before it can accept anything for a ticker.

Nothing previously populated `universe` at all -- every prior seed had to be
preceded by a hand-written INSERT (see README.md's history). This replaces
that manual step with the same source jobs.top20 already uses, so the list
is reproducible and moves with the market instead of being typed in once and
going stale.

    python -m db.seed_universe            # top 20, upsert into universe

Or import ensure_top20_in_universe() -- seed_fundamentals.py and
seed_price_history.py both call it at the start of their own main(), so
running either with no arguments seeds exactly the top 20 without a manual
INSERT first.

Ticker mapping: jobs.top20 (via ingestion.sources.scrip_master) returns BSE's
own unsuffixed ticker ("INFY", "M&M") -- the same registry
agents/sentiment_analysis addresses documents by. `universe.ticker` carries
an NSE suffix throughout the rest of this project (fetch_fundamentals_data.py,
fetch_price_history.py, the yfinance calls in the other two seed scripts all
assume it), so ".NS" is appended here. This assumes each top-20 name trades
on NSE under the same symbol as its BSE ticker, which holds for large-cap
names -- not guaranteed in general, but not worth a cross-exchange symbol
lookup for a top-20 seed.

`sector` is left NULL: BSE's scrip list carries no sector field, and nothing
else in this repo has one to offer at seed time (fetch_fundamentals_data.py
only *reads* universe.sector, nothing writes it). A row seeded here is
missing that column until something else fills it in.
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

from ingestion.http import HttpClient
from jobs.top20 import DEFAULT_COUNT, top_companies

from .connection import get_connection

_UPSERT_UNIVERSE_SQL = """
    INSERT INTO universe (ticker, company_name, exchange, active)
    VALUES (%s, %s, %s, TRUE)
    ON CONFLICT (ticker) DO UPDATE SET
        company_name = EXCLUDED.company_name,
        active = TRUE
"""


def _nse_ticker(bse_ticker):
    return f"{bse_ticker}.NS"


def ensure_top20_in_universe(count=DEFAULT_COUNT):
    """Fetches the top `count` BSE-listed companies by market cap and
    upserts each into `universe`. Returns the NSE-suffixed tickers upserted,
    ranked order preserved, so a caller can iterate them directly rather
    than re-querying `universe` (which may also hold tickers from outside
    this list).
    """
    with HttpClient() as client:
        companies = top_companies(client, count=count)

    rows = [
        (_nse_ticker(company["ticker"]), company["name"], "NSE")
        for company in companies
        if company.get("ticker")
    ]

    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(_UPSERT_UNIVERSE_SQL, rows)

    return [ticker for ticker, _name, _exchange in rows]


def main():
    tickers = ensure_top20_in_universe()
    print(f"universe: upserted {len(tickers)} top-20 companies")
    for ticker in tickers:
        print(f"  {ticker}")


if __name__ == "__main__":
    main()
