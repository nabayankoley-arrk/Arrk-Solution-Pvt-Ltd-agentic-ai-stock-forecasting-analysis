"""web_search — recent web news about one company, fetched at request time.

Two callers:
  - agents/chat_intent_routing/nodes/tools.py, as a fallback: when the user
    asks about a listed-but-untracked company ("Tata Steel") or one not found
    at all, there is no analysis to run, so the tool result carries recent news
    about it instead, clearly labelled as web information.
  - agents/sentiment_analysis/nodes/fetch_news.py: the news source of the
    sentiment pillar, alongside the stored transcript and annual report.

Nothing here is written to the database; results live only in the in-process
cache below.

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

import datetime
import html
import os
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

MAX_RESULTS = 5
# The article text kept per result, starting where it first names the company
# (see _focus). Tavily's text is ~1,200 characters and often opens with the
# site's menus, so a short cut from the start kept mostly boilerplate.
SNIPPET_CHARS = 700
_CONTENT_CHARS = 3000  # what is read before _focus trims it
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
    # unescape: some feeds send "Mahindra &amp; Mahindra", which would then not
    # match the company's name in _relevant.
    return _SPACE.sub(" ", html.unescape(str(text or ""))).strip()[:limit]


def _date(published):
    """The publication date as YYYY-MM-DD, or None. Search results sometimes
    carry day and month swapped (a date in the future): swapped back when that
    gives a past date, dropped otherwise, so a wrong date is never cited.
    Accepts ISO dates (DuckDuckGo) and RFC 2822 ones (Tavily: "Mon, 28 Sep 2026
    09:33:12 GMT")."""
    today = datetime.date.today()
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(published or ""))
    if not match:
        try:
            candidate = parsedate_to_datetime(str(published)).date()
        except (TypeError, ValueError, IndexError):
            return None
        return candidate.isoformat() if candidate <= today else None
    year, month, day = (int(g) for g in match.groups())
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
        "snippet": _clean(snippet, _CONTENT_CHARS),  # trimmed by _relevant
    }


def _tavily(query, days, max_results=MAX_RESULTS):
    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": os.environ["TAVILY_API_KEY"],
            "query": query,
            "topic": "news",
            "days": days,
            "max_results": max_results,
            "include_domains": list(WEB_SEARCH_DOMAINS),
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return [
        _result(r.get("title"), r.get("url"), r.get("content"), r.get("published_date"))
        for r in response.json().get("results") or []
    ]


def _duckduckgo(query, days, max_results=MAX_RESULTS):
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


# Trailing words only: "Titan Company Ltd" -> "Titan", but "Life Insurance
# Corporation of India" keeps its "Corporation".
_NAME_SUFFIX = re.compile(r"(\s+(ltd|limited|pvt|private|company|co|corporation|corp|inc)\b\.?)+\s*$", re.IGNORECASE)


_AMPERSAND = re.compile(r"\s*&\s*")


def _name_terms(company):
    """What a relevant result must mention: the name without "Ltd" and the like."""
    return _SPACE.sub(" ", _NAME_SUFFIX.sub(" ", company)).strip().lower()


def _query_name(company, keep_suffix=False):
    """The name as a search query: "&" spelled "and" (a bare "&" makes Tavily
    lose the company: "Mahindra & Mahindra Limited" returned only unrelated
    market news), and without "Ltd" and the like unless keep_suffix."""
    name = _AMPERSAND.sub(" and ", company)
    if not keep_suffix:
        name = _NAME_SUFFIX.sub(" ", name)
    return _SPACE.sub(" ", name).strip()


# Enough relevant articles to stop trying further phrasings.
ENOUGH_RESULTS = 3


def _tavily_queries(company):
    """Phrasings to try in order. Tavily answers a query it finds nothing for
    with generic market news, and which phrasing works varies by company:
    "Reliance Industries Ltd ..." works where "Reliance Industries ..." fails,
    "Infosys ..." where "Infosys Ltd ..." fails. Tried across the tracked
    companies, these four found news for 20 of 23, most on the first query."""
    full, short = _query_name(company, keep_suffix=True), _query_name(company)
    queries = [f"{full} share price stock news", f"{short} share price stock news", f"{short} shares", f"{short} news"]
    return list(dict.fromkeys(queries))  # a name with no suffix gives duplicates


def _name_pattern(company):
    """Matches the company's name as articles write it: case-insensitive, and
    "&" or "and" alike ("Mahindra & Mahindra", "Mahindra and Mahindra")."""
    words = _name_terms(_query_name(company)).split()
    if not words:
        return None
    parts = [re.escape(words[0])]
    for previous, word in zip(words, words[1:]):
        if word == "and":
            parts.append(r"\s*(?:&|and)\s*")
        else:
            parts.append(("" if previous == "and" else r"\s+") + re.escape(word))
    return re.compile(r"(?<![a-z0-9])" + "".join(parts) + r"(?![a-z0-9])", re.IGNORECASE)


# Quote, live-price and topic-listing pages: they mention the company but are
# not a news story ("M&M Share Price Today, M&M Stock Price Live NSE/BSE
# Updates", "Reliance Industries News - ... Latest News on Reliance ...").
_NOT_A_STORY = re.compile(
    r"(share|stock) price(\s*[,:|]|\s+(today|live|highlights|history|updates))|"
    r"price live|live nse/bse|latest news on|competitors list",
    re.IGNORECASE,
)


def _focus(text, pattern, limit=SNIPPET_CHARS):
    """The article text from where it first names the company, cut at a word
    boundary: skips the menus and captions a page's text often opens with."""
    match = pattern.search(text)
    if match:
        text = text[match.start():]
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def _relevant(results, company, limit=MAX_RESULTS):
    """News stories that mention the company, from the reputable domains first;
    other sources only when those have nothing. Each snippet starts where the
    article names the company."""
    pattern = _name_pattern(company)
    if pattern is None:
        return []
    mentions = [
        {**r, "snippet": _focus(r["snippet"], pattern)}
        for r in results
        if pattern.search(f"{r['title']} {r['snippet']}") and not _NOT_A_STORY.search(r["title"])
    ]
    trusted = [r for r in mentions if any(r["source"] == d or r["source"].endswith("." + d) for d in WEB_SEARCH_DOMAINS)]
    return (trusted or mentions)[:limit]


def search_company_news(company, days=30, max_results=MAX_RESULTS):
    """{"available", "provider", "query", "results": [...]} for recent news on `company`,
    at most `max_results` articles published in the last `days` days."""
    name = provider()
    if name is None:
        return {"available": False, "reason": "web search is not configured on this server"}

    # DuckDuckGo already merges two phrasings inside _duckduckgo.
    queries = [_query_name(company).lower()] if name == "duckduckgo" else _tavily_queries(company)
    key = (name, company, days, max_results)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    # Relevant articles from each phrasing in turn, merged by url, until enough.
    merged, tried = {}, []
    for query in queries:
        try:
            results = (_tavily if name == "tavily" else _duckduckgo)(query, days, max_results)
        except Exception as exc:
            print(f"[web_search] {name} failed for {company!r}: {type(exc).__name__}: {exc}", flush=True)
            if merged:
                break  # keep what the earlier phrasings found
            return {"available": False, "provider": name, "reason": "web search failed right now"}
        tried.append(query)
        for result in _relevant(results, company, max_results):
            merged.setdefault(result["url"], result)
        if len(merged) >= ENOUGH_RESULTS:
            break

    payload = {"available": True, "provider": name, "query": tried[-1], "queries_tried": tried,
               "results": list(merged.values())[:max_results]}
    _cache[key] = (time.monotonic(), payload)
    return payload
