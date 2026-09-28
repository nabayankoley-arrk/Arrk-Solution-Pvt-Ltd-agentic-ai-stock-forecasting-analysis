"""Report what is in the database, and load schema.sql into it.

    python -m db.apply_schema --check   # report only, change nothing
    python -m db.apply_schema           # load schema.sql

schema.sql's own header gives the psql equivalent, which remains the reference
way to load it. This exists because `psql` is not on the PATH on every
machine here, and because --check answers the question worth asking before any
job writes a row: is the database reachable, and are the tables it needs there?

Everything in schema.sql is CREATE ... IF NOT EXISTS, so applying it twice is
harmless and it never alters a table that already exists.
"""

import pathlib
import sys

import psycopg2

from .connection import get_connection

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "schema.sql"

# Reported separately because they are what this project's own code reads and
# writes. Anything else in the database belongs to someone else.
EXPECTED_TABLES = (
    ("public", "universe"),
    ("public", "financial_statements"),
    ("public", "analyst_price_targets"),
    ("public", "analyst_rating_changes"),
    ("public", "fundamental_analysis_results"),
    ("public", "orchestrator_runs"),
    ("public", "document_summaries"),
    ("Technical", "price_history"),
    ("Technical", "technical_analysis_results"),
    ("Memory", "conversation_history"),
)

_FOUND = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name
"""


def _connection_target():
    """Where we are pointed, for the report. Never includes the password."""
    import os

    return (
        f"{os.environ.get('DB_USER', 'postgres')}@"
        f"{os.environ.get('DB_HOST', 'localhost')}:"
        f"{os.environ.get('DB_PORT', '5432')}/"
        f"{os.environ.get('DB_NAME', 'stock_analysis')}"
    )


def report():
    print(f"Target  : {_connection_target()}")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        print(f"Server  : {cur.fetchone()[0].split(',')[0]}")
        cur.execute(_FOUND)
        found = {(row[0], row[1]) for row in cur.fetchall()}

    print(f"\nTables ({len(found)} present):")
    for schema, table in EXPECTED_TABLES:
        mark = "ok     " if (schema, table) in found else "MISSING"
        qualified = table if schema == "public" else f'"{schema}".{table}'
        print(f"  {mark}  {qualified}")

    extra = sorted(found - set(EXPECTED_TABLES))
    if extra:
        print("\nAlso present, not owned by this project:")
        for schema, table in extra:
            print(f"           {schema}.{table}")

    missing = [pair for pair in EXPECTED_TABLES if pair not in found]
    if missing:
        print(f"\n{len(missing)} table(s) missing. Run 'python -m db.apply_schema' to create them.")
        return 1
    print("\nEverything this project needs is present.")
    return 0


def apply():
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
    print(f"Applied {SCHEMA_PATH.name}.\n")
    return report()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        return report() if "--check" in argv else apply()
    except psycopg2.OperationalError as exc:
        # The same exception a missing or wrong DB_PASSWORD raises, which is
        # what every other caller in this project already catches.
        print(f"Cannot reach {_connection_target()}:\n  {str(exc).strip()}", file=sys.stderr)
        print(
            "\nSet DB_HOST, DB_PORT, DB_NAME, DB_USER and DB_PASSWORD, in your shell or\n"
            "in backend/.env (loaded by bootstrap.py), and check the server is running.",
            file=sys.stderr,
        )
        return 2
    except psycopg2.Error as exc:
        print(f"Database error: {str(exc).strip()}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
