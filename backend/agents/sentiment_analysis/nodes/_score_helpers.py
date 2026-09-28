"""_score_helpers.py — the one scoring step behind score_transcript and score_annual_report.

A document's score is its sentiment profile (see ../profile.py), stored on its
document_summaries row. It is used as-is when it was built with the current
prompts.PROMPT_VERSION. Otherwise -- never profiled, or built with older
prompts -- and when config.RESCORE_ON_CACHE_MISS allows it, the profile is
built from the stored summary with one LLM call and written back, so each
document costs one call per prompt version.

The LLM client is imported lazily, inside the call: this subgraph is imported
by agents/orchestrator/nodes/_pillar_runners, and agents/orchestrator eagerly
builds its own graph on import, so a module-level import of
agents.orchestrator.llm_client here would be circular.
"""

import psycopg2

from db.upsert import save_document_sentiment

from .. import prompts
from ..config import RESCORE_ON_CACHE_MISS
from ..profile import build_profile


def _model_label():
    from agents.orchestrator import config as llm_config

    if llm_config.LLM_PROVIDER == "ollama":
        return f"ollama/{llm_config.OLLAMA_MODEL}"
    return f"{llm_config.LLM_PROVIDER}/{llm_config.OPENROUTER_MODEL}"


def _score(profile, doc, source):
    return {
        "label": profile["label"],
        "direction": profile["label"],  # the label scale is the direction scale
        "profile": profile,
        "citation": doc.get("source_url") or doc.get("report_name"),
        "source": source,
    }


def score_document(doc, report_type):
    """doc: one row from ._fetch_helpers.fetch_latest_document, or None when
    that source had nothing available (the fetch node already recorded why).

    Returns {"label", "direction", "profile", "citation", "source"} with
    source "cached" | "scored", or {"label": None, "direction": None,
    "error", ...} when scoring failed; None when there was no document.
    """
    if doc is None:
        return None

    stored = doc.get("sentiment_profile")
    if stored and doc.get("sentiment_prompt_version") == prompts.PROMPT_VERSION:
        return _score(stored, doc, "cached")

    if not RESCORE_ON_CACHE_MISS:
        return None

    from agents.orchestrator.llm_client import call_llm_chat

    try:
        profile = build_profile(
            call_llm_chat, report_type, doc.get("company_name"), doc.get("report_name"),
            doc.get("filed_on"), doc.get("summary"),
        )
    except Exception as exc:
        return {
            "label": None,
            "direction": None,
            "profile": None,
            "error": f"scoring failed: {exc}",
            "citation": doc.get("source_url") or doc.get("report_name"),
            "source": "error",
        }

    if doc.get("sha256"):
        try:
            save_document_sentiment(doc["sha256"], profile, prompts.PROMPT_VERSION, _model_label())
        except psycopg2.Error:
            pass  # best-effort cache write; the score below is still returned
    return _score(profile, doc, "scored")
