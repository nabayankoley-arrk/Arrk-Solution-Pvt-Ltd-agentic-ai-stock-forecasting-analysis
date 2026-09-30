"""fetch_news — data access node, live.

Searches recent news about the company at request time (agents/web_search.py:
Tavily or DuckDuckGo, limited to reputable financial domains) over the last
config.NEWS_LOOKBACK_DAYS. Unlike fetch_transcript and fetch_annual_report,
nothing is read from or written to the database: the articles exist only in
this request's state (and web_search's short in-process cache).

The search is by company name, which is looked up in `universe`; when that
fails the unsuffixed ticker is searched instead. No web search provider
configured, a failed search or no relevant article all report the source as
"unavailable", never as an error of the pillar.
"""

import datetime

from agents.web_search import search_company_news
from db.connection import get_connection

from ..config import NEWS_ENABLED, NEWS_LOOKBACK_DAYS, NEWS_MAX_ARTICLES


def _company_name(ticker):
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT company_name FROM universe WHERE ticker = %s", (ticker,))
            row = cur.fetchone()
    except Exception:
        row = None
    return (row and row[0]) or ticker.split(".")[0]


def _as_text(articles):
    """The articles as the model reads them: one numbered block per article."""
    return "\n\n".join(
        f"[{i}] {a['title']}\nSource: {a['source'] or 'unknown'}, {a['published'] or 'date unknown'}\n{a['snippet']}"
        for i, a in enumerate(articles, 1)
    )


def _unavailable(reason):
    return {"news_doc": None, "pillar_status": {"news": "unavailable"}, "errors": {"news": reason}}


def fetch_news(state):
    if not NEWS_ENABLED:
        return _unavailable("news source disabled (SENTIMENT_NEWS_ENABLED)")
    ticker = state.get("ticker")
    company = _company_name(ticker)
    found = search_company_news(company, days=NEWS_LOOKBACK_DAYS, max_results=NEWS_MAX_ARTICLES)
    if not found.get("available"):
        return _unavailable(found.get("reason") or "web search unavailable")
    articles = found.get("results") or []
    if not articles:
        return _unavailable(f"no recent news found for {company!r} in the last {NEWS_LOOKBACK_DAYS} days")

    dates = sorted(datetime.date.fromisoformat(a["published"]) for a in articles if a.get("published"))
    today = datetime.date.today()
    doc = {
        "company_name": company,
        "report_name": f"Recent news ({len(articles)} articles, last {NEWS_LOOKBACK_DAYS} days)",
        "filed_on": dates[-1] if dates else None,
        "summary": _as_text(articles),
        "articles": articles,
        # The median article's age, so a burst of old coverage counts for less.
        "age_days": (today - dates[len(dates) // 2]).days if dates else None,
        "provider": found.get("provider"),
    }

    return {"news_doc": doc, "pillar_status": {"news": "ok"}, "errors": {"news": None}}
