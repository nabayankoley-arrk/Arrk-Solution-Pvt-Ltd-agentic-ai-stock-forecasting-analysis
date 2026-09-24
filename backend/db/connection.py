"""Database connection for this project.

Reads connection details from the environment (DB_HOST, DB_PORT, DB_NAME,
DB_USER, DB_PASSWORD) -- the same variable names used elsewhere in this
project's local tooling -- rather than hardcoding any default credentials
here. Set these in your shell or a local, gitignored .env before importing
this module; see backend/db/schema.sql for the schema to load first.

Every current caller (agents/chat_intent_routing/nodes/_ticker_lookup.py,
agents/orchestrator/nodes/_current_price.py,
agents/fundamental_analysis/nodes/fetch_fundamentals_data.py) already
catches psycopg2.OperationalError specifically to degrade gracefully
(empty memory, missing current price, pillar marked "error") instead of
crashing the whole request -- a missing/wrong DB_PASSWORD naturally raises
that same exception type via psycopg2.connect, so no extra handling is
needed here for that case.
"""

import bootstrap  # noqa: F401  -- .env + OS trust store; must precede env reads

import os

import psycopg2


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "stock_analysis"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
