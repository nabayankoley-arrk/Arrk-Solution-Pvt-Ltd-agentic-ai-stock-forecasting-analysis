"""Shared state object threaded through every node in the graph.

Field set covers the three sources this package implements: the stored
transcript and annual report, and recent news searched at request time
(see __init__.py).
"""

from typing import Annotated, Optional, TypedDict


def _merge_dicts(current, update):
    """Reducer for pillar_status/errors.

    fetch_transcript, fetch_annual_report and fetch_news run concurrently (see
    graph.py) and each contributes only its own source's key. Without an
    explicit reducer, two nodes writing to the same top-level state key in
    one superstep raises LangGraph's InvalidUpdateError -- same reasoning
    as agents/orchestrator/state.py's own _merge_dicts.
    """
    return {**(current or {}), **(update or {})}


class SentimentAnalysisState(TypedDict, total=False):
    # --- request input ---
    ticker: str

    # --- validate_input ---
    is_valid: bool
    validation_error: Optional[str]

    # --- fetch_transcript / fetch_annual_report ---
    # Each doc: a document_summaries row -- {company_name, report_name, filed_on,
    # summary, source_url, sha256, model, created_at, sentiment_profile,
    # sentiment_prompt_version, age_days} -- or None when that source is unavailable.
    transcript_doc: Optional[dict]
    annual_report_doc: Optional[dict]

    # --- fetch_news ---
    # Built from a live web search, never stored: {company_name, report_name,
    # filed_on (newest article's date), summary (the articles as text),
    # articles: [{title, source, url, published, snippet}], age_days} or None.
    news_doc: Optional[dict]

    pillar_status: Annotated[dict, _merge_dicts]  # {"transcript": "ok"|"unavailable"|"error", "annual_report": ..., "news": ...}
    errors: Annotated[dict, _merge_dicts]  # {"transcript": "reason" | None, "annual_report": ..., "news": ...}

    # --- score_transcript / score_annual_report / score_news ---
    # Each: {"label", "direction", "profile", "citation", "source": "cached"|"scored"|"error"}
    # (see nodes/_score_helpers.py), or None when the doc was unavailable.
    transcript_score: Optional[dict]
    annual_report_score: Optional[dict]
    news_score: Optional[dict]  # same shape; source "live" | "memory" | "error"

    # --- combine_sentiment_signals ---
    combined_sentiment: Optional[dict]

    # --- terminal nodes ---
    error: Optional[dict]
    final_output: Optional[dict]
