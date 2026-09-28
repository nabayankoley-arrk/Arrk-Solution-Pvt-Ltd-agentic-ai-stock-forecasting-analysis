"""_ticker_lookup — the companies this system can analyse, from `universe`.

tracked_companies() gives the agent's prompt the list to choose from, and
resolve_tracked_ticker() maps what the LLM passed to analyze_stock back to an
exact NSE ticker, so a hallucinated or loosely named company never reaches the
Orchestrator. Accepted forms, case-insensitive:

    "INFY.NS" (ticker)   "INFY" (bare symbol)   "Infosys Ltd" (company name)
    "Infosys" (short name: company_name without trailing corporate words)
    a phrase containing a short name ("Infosys Limited shares")

Short names are matched as whole phrases, longest first, since several
companies share a word ("Kotak Mahindra Bank", "Mahindra & Mahindra").

Cached in-process for CACHE_TTL_SECONDS: `universe` is ~20 rows and changes
only when db/seed_universe.py is re-run. Degrades to an empty list on any
database problem rather than raising.
"""

import re
import time

import psycopg2

from db.connection import get_connection

CACHE_TTL_SECONDS = 300

# Trailing words stripped off company_name to get its short name -- generic
# corporate words nobody types to mean one specific company. Stripped
# repeatedly, so multi-word tails ("of India") come off in one pass.
_SUFFIX_WORDS = (
    "ltd", "limited", "inc", "incorporated", "corp", "corporation", "co", "company",
    "plc", "llc", "group",
    "of", "india", "industries", "industry", "enterprises", "enterprise",
    "and", "special", "economic", "zone", "ports", "port",
)

_cache = {"expires_at": 0.0, "companies": [], "aliases": {}, "short_names": []}


def _short_name(company_name):
    words = (company_name or "").split()
    while words and words[-1].strip(".,").lower() in _SUFFIX_WORDS:
        words.pop()
    return " ".join(words).lower()


def _load():
    now = time.monotonic()
    if now < _cache["expires_at"]:
        return

    try:
        conn = get_connection()
    except psycopg2.OperationalError:
        return  # keep serving the stale cache (or the empty default) rather than raise
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, company_name FROM universe WHERE active")
            rows = cur.fetchall()
    except psycopg2.Error:
        return
    finally:
        conn.close()

    aliases, short_names = {}, []
    for ticker, company_name in rows:
        short = _short_name(company_name)
        for alias in (ticker, ticker.split(".")[0], company_name, short):
            if alias:
                aliases[alias.lower()] = ticker
        if short:
            short_names.append((short, ticker))
    short_names.sort(key=lambda pair: len(pair[0]), reverse=True)

    _cache.update(
        expires_at=now + CACHE_TTL_SECONDS,
        companies=sorted((ticker, company_name) for ticker, company_name in rows),
        aliases=aliases,
        short_names=short_names,
    )


def tracked_companies():
    """[(ticker, company_name), ...] for every active `universe` row, sorted by ticker."""
    _load()
    return list(_cache["companies"])


def resolve_tracked_ticker(raw):
    """The tracked NSE ticker `raw` refers to, or None. When `universe` cannot be
    read, `raw` is passed through as-is and the Orchestrator decides."""
    if not raw:
        return None
    _load()
    if not _cache["aliases"]:
        return str(raw).strip().upper()

    lowered = str(raw).strip().lower()
    if lowered in _cache["aliases"]:
        return _cache["aliases"][lowered]
    for short_name, ticker in _cache["short_names"]:
        if re.search(r"(?<![a-z0-9])" + re.escape(short_name) + r"(?![a-z0-9])", lowered):
            return ticker
    return None
