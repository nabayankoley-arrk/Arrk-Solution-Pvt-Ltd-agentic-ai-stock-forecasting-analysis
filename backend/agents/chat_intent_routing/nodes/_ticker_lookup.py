"""_ticker_lookup — the companies this system can analyse, from `universe`.

tracked_companies() gives the agent's prompt the list to choose from, and
resolve_tracked_ticker() maps what the LLM passed to analyze_stock ("Infosys",
"TCS") back to an exact NSE ticker ("INFY.NS"), so a hallucinated or loosely
named company never reaches the Orchestrator.

Name matching, both built from the same `universe` query:
  1. Bare ticker symbol ("TCS", "INFY", "M&M") as a whole word, case-insensitive.
  2. Company short name, derived by stripping trailing corporate-suffix words
     (_SUFFIX_WORDS) off `company_name` -- "Infosys Ltd" -> "Infosys". Matched
     as a whole phrase, since several companies share a word ("Kotak Mahindra
     Bank" and "Mahindra & Mahindra").

Cached in-process for CACHE_TTL_SECONDS: `universe` is ~20 rows and changes
only when db/seed_universe.py is re-run. Degrades to "no match" / an empty
list on any database problem rather than raising.
"""

import re
import time

import psycopg2

from db.connection import get_connection

CACHE_TTL_SECONDS = 300

# Trailing tokens stripped off company_name to get a "short name" -- generic
# corporate/legal-entity words that are never themselves what a caller types
# to mean one specific company. Stripped repeatedly from the end so multi-word
# tails ("of India", "and Special Economic Zone") come off in one pass.
_SUFFIX_WORDS = (
    "ltd", "limited", "inc", "incorporated", "corp", "corporation", "co", "company",
    "plc", "llc", "group",
    "of", "india", "industries", "industry", "enterprises", "enterprise",
    "and", "special", "economic", "zone", "ports", "port",
)

_WORD_RE = re.compile(r"[a-z0-9&]+")

_cache = {"expires_at": 0.0, "by_ticker": {}, "short_names": [], "companies": []}


def _short_name(company_name):
    words = (company_name or "").split()
    while words and words[-1].strip(".,").lower() in _SUFFIX_WORDS:
        words.pop()
    return " ".join(words)


def _bse_ticker(nse_ticker):
    """"INFY.NS" -> "INFY" -- the bare symbol a caller is more likely to
    type than the exchange-suffixed form."""
    return nse_ticker.split(".")[0]


def _load(force=False):
    now = time.monotonic()
    if not force and now < _cache["expires_at"]:
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

    by_ticker = {}
    short_names = []
    for ticker, company_name in rows:
        by_ticker[_bse_ticker(ticker).upper()] = ticker
        short = _short_name(company_name)
        if short:
            short_names.append((short.lower(), ticker))

    # Longest short name first, so "Kotak Mahindra Bank" is tried before any
    # shorter name that happens to be one of its words could be considered --
    # matching is a phrase-containment check below, not word-by-word, but
    # this keeps the most specific match first regardless.
    short_names.sort(key=lambda pair: len(pair[0]), reverse=True)

    companies = sorted((ticker, company_name) for ticker, company_name in rows)
    _cache.update(
        expires_at=now + CACHE_TTL_SECONDS, by_ticker=by_ticker, short_names=short_names, companies=companies
    )


def tracked_companies():
    """[(ticker, company_name), ...] for every active `universe` row, sorted by ticker."""
    _load()
    return list(_cache["companies"])


def resolve_ticker_from_text(message):
    """The NSE-suffixed ticker for the first company_name or bare ticker
    symbol found in `message`, or None. Case-insensitive; matches a whole
    word (ticker) or whole phrase (company short name), never a bare
    substring, so e.g. "titan" does not fire on "he was a titanic figure".
    """
    if not message:
        return None

    _load()

    lowered = message.lower()
    words = set(_WORD_RE.findall(lowered))

    for symbol, ticker in _cache["by_ticker"].items():
        if symbol.lower() in words:
            return ticker

    for short_name, ticker in _cache["short_names"]:
        if short_name in lowered:
            # Phrase-containment already checked; require it not just be
            # sitting inside a longer unrelated word on either edge.
            pattern = r"(?<![a-z0-9])" + re.escape(short_name) + r"(?![a-z0-9])"
            if re.search(pattern, lowered):
                return ticker

    return None


def resolve_tracked_ticker(raw):
    """The tracked NSE ticker `raw` refers to -- an exact ticker, a bare symbol
    ("TCS") or a company name ("Infosys") -- or None. When `universe` cannot be
    read, `raw` is passed through as-is and the Orchestrator decides."""
    if not raw:
        return None
    candidate = str(raw).strip().upper()
    tracked = {ticker.upper(): ticker for ticker, _ in tracked_companies()}
    if not tracked:
        return candidate
    return tracked.get(candidate) or tracked.get(f"{candidate}.NS") or resolve_ticker_from_text(str(raw))
