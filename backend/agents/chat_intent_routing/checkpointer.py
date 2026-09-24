"""The chat graph's checkpointer: LangGraph's conversation memory.

A PostgresSaver keyed on the caller's session_id (as LangGraph's thread_id),
so each session's messages are restored on its next request and survive a
restart. Uses the same DB_* settings as db/connection.py. setup() creates
LangGraph's own checkpoint tables on first run and is a no-op after that.

Falls back to an in-process MemorySaver, with a warning, when Postgres is
unreachable at startup: conversations then still work, but only until the
process restarts.
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import os

from langgraph.checkpoint.memory import MemorySaver

_POOL_WAIT_SECONDS = 5


def _conninfo():
    from psycopg.conninfo import make_conninfo

    return make_conninfo(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "stock_analysis"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def build_checkpointer():
    pool = None
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            conninfo=_conninfo(),
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row, "connect_timeout": 3},
            open=True,
        )
        pool.wait(timeout=_POOL_WAIT_SECONDS)
        saver = PostgresSaver(pool)
        saver.setup()
        return saver
    except Exception as exc:
        if pool is not None:
            pool.close()  # stop its background workers retrying a dead server
        print(
            f"[chat] Postgres checkpointer unavailable ({type(exc).__name__}: {exc}); "
            "conversations will not survive a restart.",
            flush=True,
        )
        return MemorySaver()
