"""_score_helpers.py — shared LLM scoring logic for score_transcript_tone
and score_annual_report_sentiment.

Both score nodes are the same bounded LLM step -- "structured output,
always run, no branching" per the specification's Architecture section --
over a different label taxonomy and a different document slot in state.
This is where that one shape lives; each score node file only supplies
its own system prompt and label set.

Routed through agents.orchestrator.llm_client.call_llm_chat(), the same
provider-agnostic entry point ingestion/summarise.py already uses, so
provider/model/key come from agents/orchestrator/config.py and the
environment -- this module never picks a provider of its own. Imported
lazily, inside score_document() rather than at module load time: this
subgraph is itself imported by agents/orchestrator/nodes/_pillar_runners
(run_sentiment), and agents/orchestrator/__init__.py eagerly builds its
own graph on import -- a module-level `from agents.orchestrator.llm_client
import ...` here would make that a circular import.

A document that already carries a stored sentiment_label (written by an
earlier call to this same node, see db.upsert.save_document_sentiment) is
passed through unchanged -- the specification's "Document already carries
a stored score -> pass it through unchanged" edge. Anything else is
scored live and, when config.RESCORE_ON_CACHE_MISS is True (the
default), the result is written back onto that document_summaries row so
the next request for the same document is a cache hit -- there being no
separate ingestion-time Score step yet (see this package's own
__init__.py).
"""

import psycopg2

from db.upsert import save_document_sentiment

from ..config import RESCORE_ON_CACHE_MISS


def _model_label():
    from agents.orchestrator import config as llm_config

    if llm_config.LLM_PROVIDER == "ollama":
        return f"ollama/{llm_config.OLLAMA_MODEL}"
    return f"{llm_config.LLM_PROVIDER}/{llm_config.OPENROUTER_MODEL}"


def score_document(doc, system_prompt, valid_labels, label_to_direction):
    """doc: one row from ._fetch_helpers.fetch_latest_document, or None
    when that source had nothing available (fetch_transcript/
    fetch_annual_report already recorded why in pillar_status/errors --
    this just passes None straight through).

    Returns {"label", "direction", "rationale", "citation", "source"} --
    "source" is "cached" | "scored" | "error", kept for callers/debugging,
    not part of the specification's own response shape.
    """
    if doc is None:
        return None

    citation = doc.get("source_url") or doc.get("report_name")

    stored_label = doc.get("sentiment_label")
    if stored_label in valid_labels:
        return {
            "label": stored_label,
            "direction": label_to_direction[stored_label],
            "rationale": doc.get("sentiment_rationale") or "",
            "citation": citation,
            "source": "cached",
        }

    if not RESCORE_ON_CACHE_MISS:
        return None

    from agents.orchestrator.llm_client import LLMAgentError, call_llm_chat, extract_json_object

    user_prompt = (
        f"Document: {doc.get('report_name') or '(untitled)'}\n"
        f"Filed: {doc.get('filed_on') or 'unknown'}\n\n"
        f"{doc.get('summary') or ''}"
    )

    try:
        raw = call_llm_chat(system_prompt, user_prompt)
        parsed = extract_json_object(raw)
        label = parsed.get("label")
        if label not in valid_labels:
            raise LLMAgentError(f"unexpected label: {label!r}")
        rationale = parsed.get("rationale") or ""
    except Exception as exc:
        return {
            "label": None,
            "direction": None,
            "rationale": f"scoring failed: {exc}",
            "citation": citation,
            "source": "error",
        }

    sha256 = doc.get("sha256")
    if sha256:
        try:
            save_document_sentiment(sha256, label, rationale, _model_label())
        except psycopg2.Error:
            pass  # best-effort cache write; the score below is still returned to the caller

    return {
        "label": label,
        "direction": label_to_direction[label],
        "rationale": rationale,
        "citation": citation,
        "source": "scored",
    }
