"""score_annual_report_sentiment — bounded LLM step.

Produces a structured sentiment read of the latest annual report's stored
summary -- bullish/neutral/bearish. Stands in for the specification's
score_coverage_report (see this package's __init__.py for why): an annual
report carries no analyst rating or price target to reason about, so it
is scored on the same bullish/neutral/bearish scale the specification
otherwise reserves for news, rather than that node's "thesis/reasoning"
scale. Every score carries a citation back to its source document.
"""

from ._score_helpers import score_document

VALID_LABELS = ("bullish", "neutral", "bearish")

LABEL_TO_DIRECTION = {"bullish": "bullish", "neutral": "neutral", "bearish": "bearish"}

SYSTEM_PROMPT = """You read a short factual summary of an Indian listed company's annual report \
and judge the overall sentiment its narrative conveys about the company's direction -- not a \
credit or valuation opinion, just whether the tone of what was reported reads as bullish, neutral \
or bearish for the business going forward.

Respond with ONLY a single JSON object, no other text, matching this shape:
{"label": "bullish" | "neutral" | "bearish", "rationale": "one or two sentences, citing what in the summary drove this read"}

Rules:
- "bullish": growth, margin expansion, a strengthened balance sheet, or confident forward \
guidance dominate the summary.
- "bearish": declining performance, a deteriorating balance sheet, prominently flagged risks or \
litigation, or cautious/negative guidance dominate.
- "neutral": the summary is mixed, or does not lean clearly either way.
- Base the read only on what the summary states. Never infer beyond it."""


def score_annual_report_sentiment(state):
    return {
        "annual_report_sentiment": score_document(
            state.get("annual_report_doc"), SYSTEM_PROMPT, VALID_LABELS, LABEL_TO_DIRECTION
        )
    }
