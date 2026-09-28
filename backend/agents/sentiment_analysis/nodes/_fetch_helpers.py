"""_fetch_helpers.py — shared retrieval logic for fetch_transcript and fetch_annual_report.

Both fetch nodes are the same query against document_summaries for a
different report_type and lookback window (see the specification's
fetch_news/fetch_coverage_reports/fetch_transcripts node description:
"Queries sentiment_documents for embedded documents of this source type
within the configured lookback window"). This is where that one shape
lives, matching the retry pattern already used by
agents/fundamental_analysis/nodes/fetch_fundamentals_data.py and
agents/technical_analysis/nodes/fetch_price_history.py.

Ticker format note: document_summaries.ticker is the unsuffixed BSE
ticker jobs/summarise_reports.py stores (via ingestion.sources.scrip_master,
e.g. "INFY"), while the Orchestrator's `ticker` carries an NSE suffix
("INFY.NS") -- the two subgraphs address companies by different registries
(see backend/db/schema.sql's own note on document_summaries having no FK
to `universe`). Stripping everything from the first "." is enough since
BSE tickers never contain one.
"""

import datetime
import time

import psycopg2

from db.upsert import latest_document_summary_by_ticker

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 0.5


def _bse_ticker(ticker):
    return (ticker or "").split(".")[0].upper()


def fetch_latest_document(ticker, report_type, lookback_months):
    """The most recently filed document of one type for one ticker, or
    (None, status, error) when it doesn't exist, is too old, or the
    database couldn't be reached. `status` is one of 'ok' | 'unavailable'
    | 'error', matching the pillar_status vocabulary the Orchestrator and
    the other two agents already use.
    """
    bse_ticker = _bse_ticker(ticker)
    if not bse_ticker:
        return None, "unavailable", f"ticker {ticker!r} has no resolvable BSE ticker"

    last_error = None
    doc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            doc = latest_document_summary_by_ticker(bse_ticker, report_type)
            break
        except psycopg2.OperationalError as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)
        except psycopg2.Error as exc:
            # Not transient -- e.g. a column missing because db/schema.sql
            # was not re-applied. Retrying would not help.
            return None, "error", f"database query failed: {str(exc).strip()[:200]}"
    else:
        return None, "error", f"database connection failed: {last_error}"

    if doc is None:
        return None, "unavailable", f"no {report_type} summary stored for {bse_ticker!r}"

    age_days = None
    filed_on = doc.get("filed_on")
    if filed_on is not None:
        age_days = (datetime.date.today() - filed_on).days
        if age_days > lookback_months * 30:
            return None, "unavailable", (
                f"latest stored {report_type} for {bse_ticker!r} is {age_days} days old, "
                f"outside the {lookback_months}-month lookback window"
            )

    doc = dict(doc)
    doc["age_days"] = age_days
    return doc, "ok", None
