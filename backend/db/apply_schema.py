"""Create this project's tables, and report what is already there.

    python -m db.apply_schema --check   # report only, change nothing
    python -m db.apply_schema           # apply schema.sql

schema.sql uses CREATE TABLE IF NOT EXISTS throughout, so applying it twice is
harmless and it will not touch a table that already exists.
"""

import pathlib
import sys

from .connection import DatabaseNotConfigured, DatabaseUnavailable, describe, get_connection

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "schema.sql"
# The tables this file is responsible for. Anything else in the database
# belongs to someone else and is only ever reported, never altered.
OWNED_TABLES = ("document_summaries",)


def report():
    state = describe()
    if not state["configured"]:
        print("Database: not configured\n")
        print(state["error"])
        return 2
    if not state["reachable"]:
        print("Database: configured but unreachable\n")
        print(f"  {state['error']}")
        return 3

    print(f"Database: {state['database']} on {state['server']}")
    if state["tables"]:
        print(f"Existing tables ({len(state['tables'])}):")
        for name in state["tables"]:
            mine = "  <- this project" if name in OWNED_TABLES else ""
            print(f"  {name}{mine}")
    else:
        print("Existing tables: none")

    missing = [name for name in OWNED_TABLES if name not in state["tables"]]
    if missing:
        print(f"\nMissing: {', '.join(missing)}")
        print("Run 'python -m db.apply_schema' to create them.")
    else:
        print("\nEverything this project needs is present.")
    return 0


def apply():
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = get_connection()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(sql)
    finally:
        connection.close()
    print(f"Applied {SCHEMA_PATH.name}.")
    return report()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        return report() if "--check" in argv else apply()
    except DatabaseNotConfigured as exc:
        print(f"Database not configured: {exc}", file=sys.stderr)
        return 2
    except DatabaseUnavailable as exc:
        print(f"Database unavailable: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
