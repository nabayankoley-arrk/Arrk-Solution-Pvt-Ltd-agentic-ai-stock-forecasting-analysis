"""web_search — recent web results for a company the database does not track.

Used by tools.py as a fallback: when the user asks about a listed-but-untracked
company ("Tata Steel") or one not found at all, there is no analysis to run, so
the tool result carries recent news about it instead, and the agent answers
from that -- clearly labelled as web information, not the app's analysis.

Providers, first available wins:
  - Tavily (https://tavily.com), when TAVILY_API_KEY is set: a free tier,
    built for LLM agents; called over plain HTTP, so no extra package.
  - DuckDuckGo, when the `ddgs` package is installed: no key, but unofficial
    and may be rate-limited.
  - Neither: {"available": False}, and the agent says web search is not set up.

Results are limited to WEB_SEARCH_DOMAINS (reputable financial news and the
exchanges), trimmed to title / source / date / a short snippet, and cached for
CACHE_TTL_SECONDS. They are untrusted third-party text: the agent's prompt says
to treat them as information, never as instructions.
"""

import os
import re
import time
from urllib.parse import urlparse

import requests

MAX_RESULTS = 5
SNIPPET_CHARS = 350
CACHE_TTL_SECONDS = 1800
TIMEOUT_SECONDS = 15

WEB_SEARCH_DOMAINS = tuple(
    d.strip() for d in os.environ.get(
        "WEB_SEARCH_DOMAINS",
        "economictimes.indiatimes.com,moneycontrol.com,livemint.com,business-standard.com,"
        "reuters.com,thehindubusinessline.com,financialexpress.com,bseindia.com,nseindia.com",
    ).split(",") if d.strip()
)

_cache = {}
_SPACE = re.compile(r"\s+")


def provider():
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    try:
        import ddgs  # noqa: F401
        return "duckduckgo"
    except ImportError:
        return None


def _clean(text, limit=SNIPPET_CHARS):
    return _SPACE.sub(" ", str(text or "")).strip()[:limit]


def _date(published):
    """The publication date as YYYY-MM-DD, or None. Search results sometimes
    carry day and month swapped (a date in the future): swapped back when that
    gives a past date, dropped otherwise, so a wrong date is never cited."""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(published or ""))
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    today = datetime.date.today()
    for m, d in ((month, day), (day, month)):
        try:
            candidate = datetime.date(year, m, d)
        except ValueError:
            continue
        if candidate <= today:
            return candidate.isoformat()
    return None


def _result(title, url, snippet, published=None):
    return {
        "title": _clean(title, 200),
        "source": urlparse(url or "").netloc.removeprefix("www."),
        "url": url,
        "published": _date(published),
        "snippet": _clean(snippet),
    }


def _tavily(query, days):
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": os.environ["TAVILY_API_KEY"],
            "query": query,
            "topic": "news",
            "days": days,
            "max_results": MAX_RESULTS,
            "include_domains": list(WEB_SEARCH_DOMAINS),
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return [
        _result(r.get("title"), r.get("url"), r.get("content"), r.get("published_date"))
        for r in response.json().get("results") or []
    ]


def _duckduckgo(query, days):
    """DuckDuckGo news for two phrasings of the query, merged. It returns about
    ten hits a query, and site: operators dilute the search terms, so domains
    and relevance are filtered afterwards (_relevant)."""
    from ddgs import DDGS

    timelimit = "d" if days <= 1 else "w" if days <= 7 else "m" if days <= 31 else "y"
    client, seen, rows = DDGS(), set(), []
    for phrasing in (f'"{query}" shares', f"{query} news"):
        for hit in client.news(phrasing, region="in-en", timelimit=timelimit, max_results=25) or []:
            if hit.get("url") not in seen:
                seen.add(hit.get("url"))
                rows.append(_result(hit.get("title"), hit.get("url"), hit.get("body"), hit.get("date")))
    return rows


_NAME_SUFFIX = re.compile(r"\b(ltd|limited|pvt|private|company|co|corporation|corp)\b\.?", re.IGNORECASE)


def _name_terms(company):
    """What a relevant result must mention: the name without "Ltd" and the like."""
    return _SPACE.sub(" ", _NAME_SUFFIX.sub(" ", company)).strip().lower()


def _relevant(results, company):
    """Results that mention the company, from the reputable domains first; other
    sources only when those have nothing."""
    terms = _name_terms(company)
    mentions = [r for r in results if terms and terms in f"{r['title']} {r['snippet']}".lower()]
    trusted = [r for r in mentions if any(r["source"] == d or r["source"].endswith("." + d) for d in WEB_SEARCH_DOMAINS)]
    return (trusted or mentions)[:MAX_RESULTS]


def search_company_news(company, days=30):
    """{"available", "provider", "query", "results": [...]} for recent news on `company`."""
    name = provider()
    if name is None:
        return {"available": False, "reason": "web search is not configured on this server"}

    query = _name_terms(company) if name == "duckduckgo" else f"{company} share price stock news"
    key = (name, query, days)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    try:
        results = (_tavily if name == "tavily" else _duckduckgo)(query, days)
    except Exception as exc:
        print(f"[chat] web search ({name}) failed for {company!r}: {type(exc).__name__}: {exc}", flush=True)
        return {"available": False, "provider": name, "reason": "web search failed right now"}

    payload = {"available": True, "provider": name, "query": query, "results": _relevant(results, company)}
    _cache[key] = (time.monotonic(), payload)
    return payload
