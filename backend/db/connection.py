"""Postgres connections for the backend.

This module did not exist before. The agent packages under backend/agents/
import `from db.connection import get_connection`, but no db package was ever
committed, so those imports fail today. This provides the function they expect,
with the same name and signature, so adding it can only help them.

Configuration comes from the environment, in this order:

    DATABASE_URL     a full libpq URL, e.g. postgresql://user:pw@host:5432/db
    PG* variables    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD

Nothing is hardcoded and no default password is assumed: a connection that is
not configured fails with a message saying what to set, rather than silently
trying localhost and timing out.
"""

import os

import psycopg2

ENV_URL = "DATABASE_URL"
PG_VARIABLES = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")


class DatabaseNotConfigured(RuntimeError):
    """No connection details in the environment."""


class DatabaseUnavailable(RuntimeError):
    """Connection details exist, but the server did not accept them."""


def dsn():
    """The connection string, or DatabaseNotConfigured with what to set."""
    url = os.environ.get(ENV_URL)
    if url:
        return url

    present = {name: os.environ.get(name) for name in PG_VARIABLES}
    if present.get("PGDATABASE") and present.get("PGUSER"):
        parts = [
            f"host={present.get('PGHOST') or 'localhost'}",
            f"port={present.get('PGPORT') or '5432'}",
            f"dbname={present['PGDATABASE']}",
            f"user={present['PGUSER']}",
        ]
        if present.get("PGPASSWORD"):
            parts.append(f"password={present['PGPASSWORD']}")
        return " ".join(parts)

    raise DatabaseNotConfigured(
        "no database configured. Set DATABASE_URL, for example\n"
        "  DATABASE_URL=postgresql://user:password@localhost:5432/stockdb\n"
        "or set PGHOST, PGPORT, PGDATABASE, PGUSER and PGPASSWORD."
    )


def get_connection():
    """An open psycopg2 connection. The caller closes it.

    Raises DatabaseNotConfigured when nothing is set, and DatabaseUnavailable
    when the server refuses -- the two need different responses, and a bare
    OperationalError does not distinguish them.
    """
    target = dsn()
    try:
        return psycopg2.connect(target)
    except psycopg2.OperationalError as exc:
        raise DatabaseUnavailable(
            f"could not connect to Postgres: {str(exc).strip()}\n"
            "Check that the server is running and that the credentials are correct."
        ) from exc


def describe():
    """Where we would connect and what is there, for a pre-flight check.

    Returns a dict with `configured`, `reachable`, `server`, `database` and
    `tables`. Never raises: this is what a caller uses to report the state of
    the database rather than to depend on it.
    """
    report = {"configured": False, "reachable": False, "server": "", "database": "",
              "tables": [], "error": ""}
    try:
        target = dsn()
    except DatabaseNotConfigured as exc:
        report["error"] = str(exc)
        return report

    report["configured"] = True
    # Never echo the DSN itself; it usually carries a password.
    try:
        connection = psycopg2.connect(target)
    except psycopg2.OperationalError as exc:
        report["error"] = str(exc).strip()
        return report

    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT version(), current_database()")
            version, database = cursor.fetchone()
            report["server"] = version.split(",")[0]
            report["database"] = database
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            report["tables"] = [row[0] for row in cursor.fetchall()]
        report["reachable"] = True
    finally:
        connection.close()
    return report
