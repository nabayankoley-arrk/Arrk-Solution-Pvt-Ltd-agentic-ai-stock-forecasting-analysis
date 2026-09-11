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
    """No caller currently -- backend/agents/technical_analysis/nodes/
    persist_results.py is a no-op (see that file's docstring: Technical
    Analysis has no database-backed persistence yet, only live yfinance
    fetches). Kept as a no-op here too so wiring it back in later doesn't
    require adding a table this repo has no confirmed schema for -- the
    real Technical Analysis Subgraph specification's own Database Schema
    section has not been shared with this repo.
    """
    return None


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


def save_conversation_session(session_id, last_ticker, last_horizon, last_scope):
    """Upserts conversation_sessions -- the Chat Intent & Routing
    Subgraph specification's update_session_context node's own
    persistence ("Writes: updated_context, and the underlying session
    store"). Only called on a normal completed turn (see
    nodes/update_session_context.py), matching the specification's
    Architecture note that session state, like user memory, is only
    updated after a real result is produced.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversation_sessions (session_id, last_ticker, last_horizon, last_scope, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (session_id) DO UPDATE SET
                last_ticker = EXCLUDED.last_ticker,
                last_horizon = EXCLUDED.last_horizon,
                last_scope = EXCLUDED.last_scope,
                updated_at = NOW()
            """,
            (session_id, last_ticker, last_horizon, Json(last_scope)),
        )


def append_conversation_message(session_id, role, content):
    """Appends one row to conversation_messages -- the specification's
    own "Optional, for audit/debugging conversation flow" table. This
    project also uses it as the source `nodes/load_conversation_context.py`
    hydrates conversation_history from on a caller's next request, since a
    stateless HTTP endpoint has nowhere else to recover a session's prior
    turns from (see that module's docstring). Ensures conversation_sessions
    has a row first (FK requirement) via a no-op upsert of just session_id.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversation_sessions (session_id)
            VALUES (%s)
            ON CONFLICT (session_id) DO NOTHING
            """,
            (session_id,),
        )
        cur.execute(
            "SELECT COALESCE(MAX(turn_index), -1) + 1 FROM conversation_messages WHERE session_id = %s",
            (session_id,),
        )
        next_turn_index = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO conversation_messages (session_id, turn_index, role, content)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, next_turn_index, role, content),
        )


def save_user_memory(user_id, memory):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO "Memory".user_memory (user_id, watchlist, preferences, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                watchlist = EXCLUDED.watchlist,
                preferences = EXCLUDED.preferences,
                updated_at = NOW()
            """,
            (user_id, Json(memory.get("watchlist")), Json(memory.get("preferences"))),
        )
