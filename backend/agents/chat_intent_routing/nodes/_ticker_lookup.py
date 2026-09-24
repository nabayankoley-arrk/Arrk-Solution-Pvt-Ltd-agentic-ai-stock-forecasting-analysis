"""_ticker_lookup — resolves a company name or bare ticker symbol mentioned
in free text against `universe`, for parse_and_route.py's ticker resolution
step 2 (see that module's own docstring): its `_TICKER_RE` only recognizes an
explicit ".NS"/".BO"-suffixed token, so "how is TCS looking?" or "predict
prices for infosys tomorrow" resolved to no ticker at all and fell through to
"ticker is required and must be a string" from the Orchestrator's own
validate_input.py.

Deliberately a database lookup, not an LLM call: `universe` (seeded by
db/seed_universe.py from jobs.top20) already carries an exact, sourced
mapping for every company this system can actually analyze -- anything
outside it fails at fetch_price_history.py/fetch_fundamentals_data.py's own
"not found in universe" checks regardless of how well its name resolves, so
better name resolution beyond `universe` would not change what a caller can
ask about. A lookup here is also free of everything an LLM call this session
kept running into: OpenRouter's rate limits and spend caps, extra latency on
every single chat turn, and a wrong/hallucinated ticker being harder to
notice than "not found in universe" is.

Two lookups, both built from the same `universe` query:
  1. Bare ticker symbol ("TCS", "INFY", "M&M") as a whole word, case-
     insensitive -- the unsuffixed form of what _TICKER_RE already matches
     suffixed. Unambiguous, since ticker symbols are already unique.
  2. Company short name, derived by stripping a fixed set of trailing
     corporate-suffix words (Ltd, Limited, Bank, Company, ...) off
     `company_name` -- "Infosys Ltd" -> "Infosys", "Titan Company Ltd" ->
     "Titan". Matched as a whole phrase, not word-by-word: several of the
     top 20 share a word ("Kotak Mahindra Bank" and "Mahindra & Mahindra"
     both contain "Mahindra"), so a single-word match would be ambiguous.
     This means a short single word the message actually contains (e.g.
     "infosys") resolves, but a name that only shortens further in common
     speech ("Reliance" for "Reliance Industries") does not -- deliberately
     conservative rather than guessing. Extend the alias behavior by adding
     to `_SUFFIX_WORDS` (a general rule, sourced from real company_name
     values) rather than hand-listing specific companies (matching
     jobs/top20.py's own reasoning: "reproducible and sourced rather than
     hand-maintained").

Cached in-process for CACHE_TTL_SECONDS: `universe` is ~20 rows and changes
only when someone re-runs db/seed_universe.py, so refetching it on every
chat message would be a DB round trip this node has no other reason to make.
Degrades to "no match" (not an error) on any database problem, same as
load_user_memory.py/load_conversation_history.py -- a lookup failure should
fall through to the watchlist or "ticker is required", not break routing.
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

_cache = {"expires_at": 0.0, "by_ticker": {}, "short_names": []}


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

    _cache.update(expires_at=now + CACHE_TTL_SECONDS, by_ticker=by_ticker, short_names=short_names)


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
