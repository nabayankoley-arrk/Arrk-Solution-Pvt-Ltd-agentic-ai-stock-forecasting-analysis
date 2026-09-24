"""Upsert helpers matching backend/db/schema.sql.

Each function's column list matches exactly what its one caller already
builds (see that caller's own docstring for the record shape) -- no
caller needed to change when this moved from a no-op stub to a real
implementation.
"""

from psycopg2.extras import Json

from .connection import get_connection


def save_fundamental_analysis_results(record):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fundamental_analysis_results (
                ticker, as_of_date, data_tier,
                relative_valuation_class, relative_valuation_detail,
                growth_class, growth_detail,
                financial_health_class, financial_health_detail,
                analyst_consensus_class, analyst_consensus_detail,
                composite_direction, composite_confidence, risk_flags
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, as_of_date) DO UPDATE SET
                data_tier = EXCLUDED.data_tier,
                relative_valuation_class = EXCLUDED.relative_valuation_class,
                relative_valuation_detail = EXCLUDED.relative_valuation_detail,
                growth_class = EXCLUDED.growth_class,
                growth_detail = EXCLUDED.growth_detail,
                financial_health_class = EXCLUDED.financial_health_class,
                financial_health_detail = EXCLUDED.financial_health_detail,
                analyst_consensus_class = EXCLUDED.analyst_consensus_class,
                analyst_consensus_detail = EXCLUDED.analyst_consensus_detail,
                composite_direction = EXCLUDED.composite_direction,
                composite_confidence = EXCLUDED.composite_confidence,
                risk_flags = EXCLUDED.risk_flags
            """,
            (
                record.get("ticker"),
                record.get("as_of_date"),
                record.get("data_tier"),
                record.get("relative_valuation_class"),
                Json(record.get("relative_valuation_detail")),
                record.get("growth_class"),
                Json(record.get("growth_detail")),
                record.get("financial_health_class"),
                Json(record.get("financial_health_detail")),
                record.get("analyst_consensus_class"),
                Json(record.get("analyst_consensus_detail")),
                record.get("composite_direction"),
                record.get("composite_confidence"),
                Json(record.get("risk_flags")),
            ),
        )


def save_technical_analysis_results(record):
    """Upserts "Technical".technical_analysis_results on
    (ticker, analysis_date), so re-running a ticker on the same day
    refreshes that day's row instead of failing on the primary key --
    same convention as save_fundamental_analysis_results above.

    Called by backend/agents/technical_analysis/nodes/persist_results.py,
    which builds exactly the keys read below. This was previously a stub
    returning None: that node has always called it with a fully populated
    record, so every technical analysis run silently discarded its own
    results. See db/schema.sql for the table.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO "Technical".technical_analysis_results (
                ticker, analysis_date, trend, momentum, volatility,
                support_level, resistance_level, overall_direction, confidence_score,
                candlestick_pattern, pattern_direction, volume_confirmed, trend_aligned,
                entry_price, stop_loss, target_price, risk_reward_ratio, trade_status,
                technical_summary
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, analysis_date) DO UPDATE SET
                trend = EXCLUDED.trend,
                momentum = EXCLUDED.momentum,
                volatility = EXCLUDED.volatility,
                support_level = EXCLUDED.support_level,
                resistance_level = EXCLUDED.resistance_level,
                overall_direction = EXCLUDED.overall_direction,
                confidence_score = EXCLUDED.confidence_score,
                candlestick_pattern = EXCLUDED.candlestick_pattern,
                pattern_direction = EXCLUDED.pattern_direction,
                volume_confirmed = EXCLUDED.volume_confirmed,
                trend_aligned = EXCLUDED.trend_aligned,
                entry_price = EXCLUDED.entry_price,
                stop_loss = EXCLUDED.stop_loss,
                target_price = EXCLUDED.target_price,
                risk_reward_ratio = EXCLUDED.risk_reward_ratio,
                trade_status = EXCLUDED.trade_status,
                technical_summary = EXCLUDED.technical_summary
            """,
            (
                record.get("ticker"),
                record.get("analysis_date"),
                record.get("trend"),
                record.get("momentum"),
                record.get("volatility"),
                record.get("support_level"),
                record.get("resistance_level"),
                record.get("overall_direction"),
                record.get("confidence_score"),
                record.get("candlestick_pattern"),
                record.get("pattern_direction"),
                record.get("volume_confirmed"),
                record.get("trend_aligned"),
                record.get("entry_price"),
                record.get("stop_loss"),
                record.get("target_price"),
                record.get("risk_reward_ratio"),
                record.get("trade_status"),
                Json(record.get("technical_summary")),
            ),
        )


def save_price_history(ticker, rows):
    """Caches OHLCV bars fetched from yfinance into "Technical".price_history,
    so agents/orchestrator/nodes/_current_price.py (which reads only from
    that table) can resolve a current price for Fundamental Analysis.
    `rows` is the same list fetch_price_history.py already builds: dicts
    with trade_date/open_price/high_price/low_price/close_price/
    adjusted_close/volume.
    """
    if not rows:
        return None

    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO "Technical".price_history (
                ticker, trade_date, open_price, high_price, low_price, close_price, adjusted_close, volume
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, trade_date) DO UPDATE SET
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                adjusted_close = EXCLUDED.adjusted_close,
                volume = EXCLUDED.volume
            """,
            [
                (
                    ticker,
                    row["trade_date"],
                    row["open_price"],
                    row["high_price"],
                    row["low_price"],
                    row["close_price"],
                    row["adjusted_close"],
                    row["volume"],
                )
                for row in rows
            ],
        )


def save_orchestrator_run(record):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO orchestrator_runs (
                run_id, ticker, analysis_horizon,
                technical_status, fundamental_status, sentiment_status,
                selected_tool, tool_loop_count, final_decision,
                final_response, error_details,
                requires_review, reviewer_decision, review_notes,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (run_id) DO UPDATE SET
                technical_status = EXCLUDED.technical_status,
                fundamental_status = EXCLUDED.fundamental_status,
                sentiment_status = EXCLUDED.sentiment_status,
                selected_tool = EXCLUDED.selected_tool,
                tool_loop_count = EXCLUDED.tool_loop_count,
                final_decision = EXCLUDED.final_decision,
                final_response = EXCLUDED.final_response,
                error_details = EXCLUDED.error_details,
                requires_review = EXCLUDED.requires_review,
                reviewer_decision = EXCLUDED.reviewer_decision,
                review_notes = EXCLUDED.review_notes,
                updated_at = NOW()
            """,
            (
                record.get("run_id"),
                record.get("ticker"),
                record.get("analysis_horizon"),
                record.get("technical_status"),
                record.get("fundamental_status"),
                record.get("sentiment_status"),
                record.get("selected_tool"),
                record.get("tool_loop_count", 0),
                record.get("final_decision"),
                Json(record.get("final_response")),
                Json(record.get("error_details")),
                record.get("requires_review"),
                record.get("reviewer_decision"),
                record.get("review_notes"),
            ),
        )


def save_conversation_turn(record):
    """Appends one row to "Memory".conversation_history, the append-only turn
    log written by agents/chat_intent_routing/nodes/persist_conversation_turn.py.

    record: {"turn_id", "user_id", "thread_id", "message", "intent",
    "resolved_ticker", "response"}
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO "Memory".conversation_history (
                turn_id, user_id, thread_id, message, intent, resolved_ticker, response
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.get("turn_id"),
                record.get("user_id"),
                record.get("thread_id"),
                record.get("message"),
                record.get("intent"),
                record.get("resolved_ticker"),
                Json(record.get("response")),
            ),
        )


# --- document_summaries -------------------------------------------------
# Written by backend/jobs/summarise_reports.py. Unlike the functions above,
# these take no Json() columns: a summary is text, and the provenance fields
# are scalars.

# The abbreviations stored in document_summaries.report_type, matching that
# table's CHECK constraint.
REPORT_TYPES = {
    "annual_report": "AR",
    "transcript": "TR",
}


def report_type_for(doc_types):
    """AR or TR for a document's classified types, or None if it is neither.

    Annual report wins when a document is both -- companies file a combined
    report-and-AGM-notice PDF, and that is an annual report.
    """
    for doc_type in ("annual_report", "transcript"):
        if doc_type in (doc_types or []):
            return REPORT_TYPES[doc_type]
    return None


def save_document_summary(record):
    """Writes one summary, returning "inserted" or "updated".

    Keyed on the PDF's sha256, so re-running the job over documents it has
    already seen refreshes those rows rather than accumulating duplicates.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_summaries (
                scrip_code, ticker, company_name, report_name, report_type,
                filed_on, source, source_url, local_path, sha256,
                page_count, char_count, summary, model
            ) VALUES (
                %(scrip_code)s, %(ticker)s, %(company_name)s, %(report_name)s,
                %(report_type)s, %(filed_on)s, %(source)s, %(source_url)s,
                %(local_path)s, %(sha256)s, %(page_count)s, %(char_count)s,
                %(summary)s, %(model)s
            )
            ON CONFLICT (sha256) DO UPDATE SET
                scrip_code = EXCLUDED.scrip_code,
                ticker = EXCLUDED.ticker,
                company_name = EXCLUDED.company_name,
                report_name = EXCLUDED.report_name,
                report_type = EXCLUDED.report_type,
                filed_on = EXCLUDED.filed_on,
                source = EXCLUDED.source,
                source_url = EXCLUDED.source_url,
                local_path = EXCLUDED.local_path,
                page_count = EXCLUDED.page_count,
                char_count = EXCLUDED.char_count,
                summary = EXCLUDED.summary,
                model = EXCLUDED.model,
                updated_at = NOW()
            RETURNING (xmax = 0) AS inserted
            """,
            record,
        )
        return "inserted" if cur.fetchone()[0] else "updated"


def existing_document_checksums():
    """Every sha256 already summarised, so a rerun can skip the model call.

    The expensive part of that job is the model, not the download, so this is
    what makes re-running it cheap.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT sha256 FROM document_summaries")
        return {row[0] for row in cur.fetchall()}


def latest_document_summary(scrip_code, report_type):
    """The most recent stored summary of one type for one company, or None."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT report_name, filed_on, summary, source_url, model, created_at
            FROM document_summaries
            WHERE scrip_code = %s AND report_type = %s
            ORDER BY filed_on DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (str(scrip_code), report_type),
        )
        row = cur.fetchone()
    if row is None:
        return None
    keys = ("report_name", "filed_on", "summary", "source_url", "model", "created_at")
    return dict(zip(keys, row))


_DOCUMENT_SUMMARY_BY_TICKER_COLUMNS = (
    "report_name",
    "filed_on",
    "summary",
    "source_url",
    "sha256",
    "model",
    "created_at",
    "sentiment_label",
    "sentiment_rationale",
)


def latest_document_summary_by_ticker(ticker, report_type):
    """The most recent stored summary of one type for one company, looked up
    by unsuffixed BSE ticker ("INFY") rather than scrip_code.

    latest_document_summary() above answers the same question keyed on
    scrip_code, which is what jobs/summarise_reports.py writes and the stable
    identifier of the two. The analysis side does not have it: the
    Orchestrator carries an NSE-suffixed ticker, which
    agents/sentiment_analysis/nodes/_fetch_helpers.py strips to the BSE form
    before calling this. Hence two lookups over one table rather than making
    either caller translate between registries.

    Returns a dict, or None when nothing is stored. `sentiment_label` and
    `sentiment_rationale` come back so _score_helpers.py can serve a cached
    verdict without a second query; both are NULL until save_document_sentiment
    fills them in.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {", ".join(_DOCUMENT_SUMMARY_BY_TICKER_COLUMNS)}
            FROM document_summaries
            WHERE upper(ticker) = upper(%s) AND report_type = %s
            ORDER BY filed_on DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (ticker, report_type),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(_DOCUMENT_SUMMARY_BY_TICKER_COLUMNS, row))


def save_document_sentiment(sha256, label, rationale, model):
    """Caches one document's LLM sentiment verdict back onto its own row, so
    the next request for it is served without paying for the call again (see
    agents/sentiment_analysis/nodes/_score_helpers.py, which calls this
    best-effort and still returns the score if it fails).

    Keyed on sha256 -- document_summaries' natural key for a specific PDF, and
    UNIQUE -- so re-summarising the same file overwrites rather than
    duplicating. A sha256 with no matching row updates nothing and raises
    nothing; the caller has the score either way.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE document_summaries
            SET sentiment_label = %s,
                sentiment_rationale = %s,
                sentiment_model = %s,
                sentiment_scored_at = NOW(),
                updated_at = NOW()
            WHERE sha256 = %s
            """,
            (label, rationale, model, sha256),
        )
