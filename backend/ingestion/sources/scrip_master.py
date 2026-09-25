"""Resolve a ticker or company name to a BSE scrip code.

BSE addresses companies by a numeric scrip code, which nobody remembers. It
also publishes the full list of active equity scrips in one request -- roughly
5,000 rows, 1.7 MB -- carrying the code, the ticker and the registered name.
Fetching that once and searching it locally is both faster and far more
predictable than BSE's own search endpoint, which returns a rendered HTML page
rather than data.

The list is cached on disk because it changes rarely: new listings, name
changes and delistings, none of which matter within a working session.
"""

import datetime
import json
import pathlib

from .. import config, documents
from ..errors import ConfigurationError, SourceUnavailable

LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
LIST_REFERER = "https://www.bseindia.com/corporates/List_Scrips.html"

CACHE_FILENAME = "scrips.json"
# Bumped whenever _normalise() changes shape. Without it, a cache written by an
# older version is loaded happily and every new field reads as missing --
# market_cap silently zero, and "the top 20 by market cap" silently empty.
CACHE_VERSION = 2
# New listings and name changes do not matter within a week of work, and the
# list costs 1.7 MB to refetch.
CACHE_MAX_AGE_DAYS = 7


def cache_path(cache_dir=None):
    return pathlib.Path(cache_dir or config.DEFAULT_CACHE_DIR) / CACHE_FILENAME


def _load_cache(cache_dir):
    path = cache_path(cache_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
    except (ValueError, OSError):
        return None
    if not isinstance(cached, dict) or not isinstance(cached.get("entries"), list):
        return None
    if cached.get("version") != CACHE_VERSION:
        return None
    try:
        fetched_on = datetime.date.fromisoformat(cached.get("fetched_on", ""))
    except ValueError:
        return None
    if (datetime.date.today() - fetched_on).days > CACHE_MAX_AGE_DAYS:
        return None
    return cached["entries"]


def _save_cache(cache_dir, entries):
    """Best effort. A cache that cannot be written costs a refetch, nothing more."""
    path = cache_path(cache_dir)
    partial = path.with_name(path.name + config.PARTIAL_SUFFIX)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(partial, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": CACHE_VERSION,
                    "fetched_on": datetime.date.today().isoformat(),
                    "entries": entries,
                },
                handle,
            )
        partial.replace(path)
    except OSError:
        try:
            partial.unlink()
        except OSError:
            pass


def _market_cap(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalise(row):
    return {
        "scrip_code": documents.clean(row.get("SCRIP_CD")),
        "ticker": documents.clean(row.get("scrip_id")).upper(),
        "name": documents.clean(row.get("Scrip_Name")),
        "issuer": documents.clean(row.get("Issuer_Name")),
        "isin": documents.clean(row.get("ISIN_NUMBER")).upper(),
        "group": documents.clean(row.get("GROUP")),
        "industry": documents.clean(row.get("INDUSTRY")),
        # BSE reports market capitalisation in lakh; it is what ranks the
        # top-20 job. Absent or unparseable means unranked, not zero-valued.
        "market_cap": _market_cap(row.get("Mktcap")),
    }


def load(client, cache_dir=None, refresh=False):
    """Every active equity scrip, from cache when it is fresh enough."""
    if not refresh:
        cached = _load_cache(cache_dir)
        if cached is not None:
            return cached

    # Visiting the page a browser would come from first picks up the cookies
    # BSE's bot protection sets; without them the API can answer 403. Best
    # effort: if the page itself fails, the API call below reports the problem.
    try:
        client.get(LIST_REFERER).close()
    except SourceUnavailable:
        pass

    payload = client.get_json(LIST_URL, params={
        "Group": "", "Scripcode": "", "industry": "", "segment": "Equity", "status": "Active",
    }, referer=LIST_REFERER)

    if not isinstance(payload, list) or not payload:
        raise SourceUnavailable(
            "BSE returned no scrip list; expected a JSON array of active scrips"
        )

    entries = [_normalise(row) for row in payload if isinstance(row, dict)]
    entries = [entry for entry in entries if entry["scrip_code"]]
    _save_cache(cache_dir, entries)
    return entries


def search(entries, query):
    """Candidate scrips for a ticker, name, ISIN or numeric code.

    Ranked most specific first, so a caller can accept a single unambiguous
    match and otherwise show the alternatives. An exact ticker beats a company
    whose name merely contains the word, which is what makes "TCS" resolve to
    Tata Consultancy Services rather than to a list of everything with "tcs"
    somewhere in its name.
    """
    needle = (query or "").strip()
    if not needle:
        raise ConfigurationError("no company given to search for")
    folded = needle.casefold()

    tiers = ([], [], [], [], [])
    for entry in entries:
        name = entry["name"].casefold()
        issuer = entry["issuer"].casefold()
        if entry["scrip_code"] == needle:
            tiers[0].append(entry)
        elif entry["ticker"].casefold() == folded or entry["isin"].casefold() == folded:
            tiers[1].append(entry)
        elif name == folded or issuer == folded:
            tiers[2].append(entry)
        elif name.startswith(folded) or issuer.startswith(folded):
            tiers[3].append(entry)
        elif folded in name or folded in issuer:
            tiers[4].append(entry)

    ranked = []
    for tier in tiers:
        ranked.extend(sorted(tier, key=lambda entry: entry["name"]))
    return ranked


def resolve(client, query, cache_dir=None, refresh=False):
    """The single scrip a query names, or ConfigurationError listing the options.

    A purely numeric query is accepted even when it is not in the list, so that
    a newly listed or non-equity code can still be used directly.
    """
    entries = load(client, cache_dir=cache_dir, refresh=refresh)
    matches = search(entries, query)

    if not matches:
        if query.strip().isdigit():
            return {"scrip_code": query.strip(), "ticker": "", "name": "", "issuer": "",
                    "isin": "", "group": "", "industry": ""}
        raise ConfigurationError(
            f"no BSE-listed company matches {query!r}. Try a ticker (AVANTEL), a scrip "
            "code (532406), or part of the registered name."
        )

    # An exact code, ticker or ISIN is unambiguous even if other names contain
    # the same word.
    if len(matches) == 1 or matches[0]["scrip_code"] == query.strip() or (
        matches[0]["ticker"].casefold() == query.strip().casefold()
    ):
        return matches[0]

    shown = "\n".join(
        f"    {entry['scrip_code']:<8} {entry['ticker']:<12} {entry['name']}"
        for entry in matches[:12]
    )
    more = f"\n    ... and {len(matches) - 12} more" if len(matches) > 12 else ""
    raise ConfigurationError(
        f"{query!r} matches {len(matches)} companies. Name one exactly:\n{shown}{more}"
    )
