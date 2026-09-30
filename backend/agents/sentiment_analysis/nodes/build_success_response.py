"""build_success_response — terminal node.

The pillar's result: the combined direction, a one-paragraph summary, and per
source the document it came from and its sentiment profile (label,
management tone, guidance, themes, positives, concerns, quotes). For news, the
"document" is the live search, and its articles (title, source, date, url) are
listed so the answer can cite them. The stored summary text itself is left out
-- this output goes into the Orchestrator's reconciliation prompt on every run
-- and is read from the graph's state by callers that need it
(agents/chat_intent_routing's get_filing_sentiment tool).
"""

import datetime

from .combine_sentiment_signals import SOURCES

_SOURCE_LABELS = {"transcript": "Call transcript", "annual_report": "Annual report", "news": "Recent news"}
_ARTICLE_FIELDS = ("title", "source", "published", "url")
_EXCERPT_CHARS = 240


def _excerpt(text):
    text = (text or "").strip()
    return text if len(text) <= _EXCERPT_CHARS else text[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + "..."


def _articles(doc, profile):
    """News articles, the profile's top stories first (most important first),
    each with the model's summary of it; the rest after, each with an excerpt
    of its own text instead."""
    stories = {s["article"]: s["summary"] for s in (profile or {}).get("stories") or []}
    order = list(stories) + [n for n in range(1, len(doc["articles"]) + 1) if n not in stories]
    articles = []
    for n in order:
        article = doc["articles"][n - 1]
        entry = {k: article.get(k) for k in _ARTICLE_FIELDS}
        if n in stories:
            entry["summary"] = stories[n]
        else:
            entry["excerpt"] = _excerpt(article.get("snippet")) or None
        articles.append(entry)
    return articles


def _source(score, doc, status):
    if not doc:
        return {"status": status}
    entry = {
        "status": status,
        "document": doc.get("report_name"),
        "filed_on": str(doc["filed_on"]) if doc.get("filed_on") else None,
        "citation": (score or {}).get("citation"),
    }
    profile = (score or {}).get("profile")
    if doc.get("articles"):
        entry["articles"] = _articles(doc, profile)
    if profile:
        entry.update({k: v for k, v in profile.items() if k != "stories"})  # stories are in articles
    elif score and score.get("error"):
        entry.update(status="error", error=score["error"])  # found, but could not be scored
    return entry


def _summary(sources):
    parts = []
    for source, entry in sources.items():
        if entry.get("label"):
            tone = f", management {entry['management_tone']}" if entry.get("management_tone") else ""
            parts.append(f"{_SOURCE_LABELS[source]} ({entry['label']}{tone}): {entry.get('rationale') or ''}".strip())
    return " ".join(parts) or "No transcript, annual-report or news sentiment was available for this ticker."


def build_success_response(state):
    combined = state.get("combined_sentiment") or {}
    pillar_status = state.get("pillar_status") or {}
    sources = {
        source: _source(state.get(score_key), state.get(doc_key), pillar_status.get(source))
        for source, (score_key, doc_key) in SOURCES.items()
    }
    return {
        "final_output": {
            "ticker": state.get("ticker"),
            "as_of_date": datetime.date.today().isoformat(),
            "direction": combined.get("direction"),
            "score": combined.get("score"),
            "coverage": combined.get("coverage"),
            "summary": _summary(sources),
            "sources": sources,
            "source_status": {source: entry["status"] for source, entry in sources.items()},
        }
    }
