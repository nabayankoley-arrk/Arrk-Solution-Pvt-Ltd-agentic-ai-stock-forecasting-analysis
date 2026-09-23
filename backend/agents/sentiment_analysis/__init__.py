"""Sentiment Analysis Agent -- Request-Time Subgraph, transcript + annual report only.

Implements a deliberately narrowed slice of the Sentiment Analysis
Subgraph specification's Request-Time Subgraph: the transcript and
annual-report sources only. News (a continuously-refreshed, high-volume
source needing its own periodic ingestion and a live Tavily fallback) is
out of scope here -- wiring it in later only means adding a third
fetch_news/score_news_sentiment branch alongside the two below and giving
it a weight in config.SOURCE_WEIGHTS, not restructuring this package.

"Coverage report" (third-party analyst notes) does not exist as a
document type this project ingests -- backend/jobs/summarise_reports.py
(see its own README) fetches only annual reports and call transcripts,
per company, from BSE/company sites. This package uses that same
annual-report slot in place of the specification's coverage-report
source, scored on its own bullish/neutral/bearish scale rather than the
specification's coverage "thesis/reasoning" scale (an annual report
carries no analyst rating to reason about).

Two other differences from the full specification, both consequences of
what jobs/summarise_reports.py actually built (see its README and
backend/db/schema.sql's document_summaries table):

  - No separate ingestion-time embedding/scoring pipeline or vector DB.
    document_summaries already holds one summarised row per document,
    keyed on sha256 -- this subgraph scores that stored summary directly
    at request time and writes the label back onto the same row (see
    db.upsert.save_document_sentiment), so a second request for the same
    document is a cache hit. That is the specification's "Document
    already carries a stored score -> pass it through unchanged" /
    "RESCORE_ON_CACHE_MISS = true" edges collapsed into one path, since
    there is no separate ingestion-time Score step to have already run.

  - No live Tavily fallback on a cache miss. A ticker with no ingested
    transcript or annual report simply reports that source as
    "unavailable" -- ingestion (jobs.summarise_reports) is what's meant
    to keep document_summaries current ahead of a request, per the
    specification's own Architecture section.

`build_graph()` in `graph.py` assembles the compiled LangGraph state
graph; agents/orchestrator/nodes/_pillar_runners.run_sentiment is the one
caller.
"""

from .graph import build_graph

__all__ = ["build_graph"]
