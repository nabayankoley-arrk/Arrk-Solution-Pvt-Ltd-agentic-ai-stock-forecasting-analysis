"""Turn an extracted filing into a short summary, via the project's LLM client.

Routed through agents.orchestrator.llm_client.call_llm_chat(), which that
module's own docstring names as "the one provider-agnostic entry point
everything else in this package should use". So provider, model, API key and
temperature all come from agents/orchestrator/config.py and the environment
(LLM_PROVIDER, OPENROUTER_MODEL, OPENROUTER_API_KEY), and this module never
picks a provider of its own.

Annual reports are the hard case. Measured on real filings, they run from
640,000 characters (Avantel, 261 pages) to 1.9 million (State Bank of India,
756 pages). The configured default model holds 262,144 tokens, which is enough
for the smaller ones and not the larger, so a document that does not fit is
summarised in parts and those partial summaries are then summarised together.
Nothing is silently truncated: the caller is told how many parts were used, and
the stored row records the character count it was built from.
"""

import os
import re
import time

import requests

from agents.orchestrator import config as llm_config
from agents.orchestrator.llm_client import LLMAgentError, call_llm_chat

# English financial prose runs near four characters per token; tables and
# figures tokenise worse. The default model's 262,144-token context would be
# filled exactly by about a million characters, so this leaves roughly a fifth
# of the window for the system prompt, the reply, and that error. Override with
# SUMMARY_MAX_INPUT_CHARS when changing to a model with a different window.
MAX_INPUT_CHARS = int(os.environ.get("SUMMARY_MAX_INPUT_CHARS", "800000"))

# A 200,000-word prompt takes minutes, not seconds. The orchestrator's own
# 60-second default is sized for a small JSON decision and is far too short.
TIMEOUT_SECONDS = int(os.environ.get("SUMMARY_TIMEOUT_SECONDS", "600"))

# A free-tier key rate-limits per minute, and this job makes tens of calls in
# a row, so 429 is expected rather than exceptional -- wait and ask again.
# 5xx is included because a gateway hiccup is equally worth one more try;
# 4xx other than 429 (bad key, bad model id) never improves by waiting.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = int(os.environ.get("SUMMARY_MAX_ATTEMPTS", "5"))
RETRY_BASE_SECONDS = 20.0   # free limits reset per minute, so start there
RETRY_CEILING_SECONDS = 120.0

DOCUMENT_LABELS = {
    "AR": "annual report",
    "TR": "earnings or AGM call transcript",
}

SYSTEM = """You summarise filings by Indian listed companies for an equity research system.

Write a short, factual summary that an analyst can read in under a minute:

- Open with one sentence naming the company, the document and the period it covers.
- Then five to eight bullets covering, where the document supports them:
  headline financials with the actual figures, segment or business performance,
  margin and cost movements, balance sheet or cash flow changes, management's
  stated outlook and guidance, and any risk, litigation or governance matter
  given prominence.
- Close with one line on what changed versus the prior period.

Rules:
- Use only what the document states. Never infer, estimate or fill gaps.
- Quote figures with their units and currency exactly as reported.
- If the document does not cover something, leave it out rather than noting its
  absence.
- No preamble, no closing commentary, no investment recommendation.
- Plain text. No markdown headers."""

# Used on each part of a document too large for one call. Deliberately asks for
# raw material rather than a finished summary: a well-formed summary of part
# three of seven would read as though it covered the whole company.
SYSTEM_PARTIAL = """You are reading one section of a longer filing by an Indian listed company.

Extract only what a later step needs to write a summary of the whole document:

- Every reported figure, with its label, unit, currency and period.
- Statements about performance, margins, costs, cash flow and debt.
- Management's stated outlook, guidance and commentary.
- Risks, litigation and governance matters.

Rules:
- Use only what this section states. Never infer or estimate.
- Omit boilerplate, notices, page furniture and repeated headers.
- If the section carries nothing of substance, reply with exactly: NOTHING OF NOTE
- Terse notes, not prose. No preamble."""

SYSTEM_COMBINE = SYSTEM + """

You are working from ordered notes taken from consecutive sections of one
document, not from the document itself. Treat them as a single source. Where
two notes disagree, prefer the more specific figure and do not remark on the
discrepancy."""

_PARAGRAPH = re.compile(r"\n\s*\n")
_NOTHING = "NOTHING OF NOTE"


class SummaryFailed(RuntimeError):
    """The model did not return a usable summary."""


class NotConfigured(RuntimeError):
    """The LLM provider is not usable -- usually a missing API key."""


def describe_provider():
    """Provider and model in use, for a run to report before it starts."""
    if llm_config.LLM_PROVIDER == "ollama":
        return f"ollama / {llm_config.OLLAMA_MODEL}"
    return f"{llm_config.LLM_PROVIDER} / {llm_config.OPENROUTER_MODEL}"


def check_ready():
    """Raises NotConfigured if a call would certainly fail.

    Checked before any downloading, so a missing key costs a second rather than
    surfacing after twenty documents have been fetched and read.
    """
    if llm_config.LLM_PROVIDER == "openrouter" and not llm_config.OPENROUTER_API_KEY:
        raise NotConfigured(
            "OPENROUTER_API_KEY is not set, and LLM_PROVIDER is openrouter.\n"
            "Put it in backend/.env (loaded by bootstrap.py, and gitignored):\n"
            "  OPENROUTER_API_KEY=...\n"
            "  OPENROUTER_MODEL=inclusionai/ling-3.0-flash-fin:free\n"
            "Or set LLM_PROVIDER=ollama to use a local model instead."
        )
    if llm_config.LLM_PROVIDER not in ("openrouter", "ollama"):
        raise NotConfigured(f"unknown LLM_PROVIDER: {llm_config.LLM_PROVIDER!r}")


def _header(report_type, company, title, filed_on):
    label = DOCUMENT_LABELS.get(report_type, "filing")
    header = f"Company: {company}\nDocument: {title}\nType: {label}"
    if filed_on:
        header += f"\nFiled: {filed_on}"
    return header


def split(text, limit=None):
    """Split into pieces no larger than `limit`, at paragraph breaks.

    A paragraph longer than the limit on its own is cut at the limit rather
    than dropped -- losing a page of a dense table is worse than splitting one
    awkwardly.
    """
    limit = limit or MAX_INPUT_CHARS
    if len(text) <= limit:
        return [text]

    pieces, current = [], ""
    for paragraph in _PARAGRAPH.split(text):
        if len(paragraph) > limit:
            if current:
                pieces.append(current)
                current = ""
            for start in range(0, len(paragraph), limit):
                pieces.append(paragraph[start:start + limit])
            continue
        if len(current) + len(paragraph) + 2 > limit:
            pieces.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        pieces.append(current)
    return pieces


def _retry_after(exc, attempt):
    """Seconds to wait before retrying, honouring Retry-After when sent."""
    response = getattr(exc, "response", None)
    header = (response.headers.get("Retry-After") if response is not None else None)
    if header:
        try:
            return min(float(header), RETRY_CEILING_SECONDS)
        except ValueError:
            pass
    return min(RETRY_BASE_SECONDS * (2 ** attempt), RETRY_CEILING_SECONDS)


def _ask(system_prompt, user_prompt, progress=None):
    """One model call, retrying the failures that are worth retrying.

    call_llm_chat has no retry of its own -- it was written for a single small
    decision per request, where one failure just falls back to a rule. This job
    makes tens of calls in a row, and a free-tier key rate-limits well before
    it finishes: a real run summarised a 384-page report in two parts and then
    lost the next document to a 429, seconds later. Waiting and asking again is
    the whole fix.
    """
    last = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            reply = call_llm_chat(system_prompt, user_prompt, timeout=TIMEOUT_SECONDS)
        except LLMAgentError as exc:
            # A missing key never becomes valid by waiting.
            raise NotConfigured(str(exc)) from exc
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                raise SummaryFailed(f"HTTP {status}: {str(exc)[:160]}") from exc
            wait = _retry_after(exc, attempt)
            if progress:
                progress(f"  HTTP {status}, waiting {wait:.0f}s (attempt {attempt + 2} of {MAX_ATTEMPTS})")
            time.sleep(wait)
            last = exc
            continue
        except requests.RequestException as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise SummaryFailed(f"{type(exc).__name__}: {str(exc)[:160]}") from exc
            wait = _retry_after(exc, attempt)
            if progress:
                progress(f"  {type(exc).__name__}, waiting {wait:.0f}s")
            time.sleep(wait)
            last = exc
            continue
        except Exception as exc:
            raise SummaryFailed(f"{type(exc).__name__}: {str(exc)[:200]}") from exc

        if not (reply or "").strip():
            raise SummaryFailed("the model returned an empty reply")
        return reply.strip()

    raise SummaryFailed(f"gave up after {MAX_ATTEMPTS} attempts: {str(last)[:160]}")


def summarise(text, report_type, company, title, filed_on="", progress=None):
    """A short summary of one filing.

    Documents that fit the context window are summarised in one call; larger
    ones are read in parts and those notes summarised together. `progress` is
    called with a short status string when a document needs more than one call,
    since that path takes minutes.
    """
    header = _header(report_type, company, title, filed_on)
    parts = split(text)

    if len(parts) == 1:
        summary = _ask(SYSTEM, f"{header}\n\n---\n\n{text}", progress)
    else:
        if progress:
            progress(f"{len(text):,} characters: reading in {len(parts)} parts")
        notes = []
        for index, part in enumerate(parts, 1):
            if progress:
                progress(f"  part {index} of {len(parts)}")
            note = _ask(
                SYSTEM_PARTIAL,
                f"{header}\nSection {index} of {len(parts)}\n\n---\n\n{part}",
                progress,
            )
            if note.upper().startswith(_NOTHING):
                continue
            notes.append(f"--- notes from section {index} of {len(parts)} ---\n{note}")

        if not notes:
            raise SummaryFailed(
                f"all {len(parts)} sections came back empty; the text layer is "
                "probably boilerplate or the document did not extract properly"
            )
        if progress:
            progress(f"  combining {len(notes)} set(s) of notes")
        summary = _ask(
            SYSTEM_COMBINE, f"{header}\n\n---\n\n" + "\n\n".join(notes), progress
        )

    return {
        "summary": summary,
        "model": describe_provider(),
        "chunks": len(parts),
        "chars_in": len(text),
    }
