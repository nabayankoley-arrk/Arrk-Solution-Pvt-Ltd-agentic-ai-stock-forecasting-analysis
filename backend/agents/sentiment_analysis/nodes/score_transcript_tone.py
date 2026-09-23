"""score_transcript_tone — bounded LLM step.

Produces a structured read of management's tone on the latest call
transcript's stored summary -- confident/cautious/defensive, per the
specification's node description ("confident/cautious/defensive for
transcript tone"). Every score carries a citation back to its source
document.
"""

from ._score_helpers import score_document

VALID_LABELS = ("confident", "cautious", "defensive")

LABEL_TO_DIRECTION = {
    "confident": "bullish",
    "cautious": "neutral",
    "defensive": "bearish",
}

SYSTEM_PROMPT = """You read a short factual summary of an earnings-call or AGM transcript for an \
Indian listed company and judge management's tone -- not the company's underlying financial \
performance, only how management came across while discussing it.

Respond with ONLY a single JSON object, no other text, matching this shape:
{"label": "confident" | "cautious" | "defensive", "rationale": "one or two sentences, citing what in the summary drove this read"}

Rules:
- "confident": management describes performance, outlook or guidance with assurance and little \
or no hedging.
- "cautious": management flags uncertainty, softens guidance, or is measured about risks without \
sounding defensive about them.
- "defensive": management is explaining away weak results, deflecting on a risk or controversy, \
or notably hedging where confidence would be expected.
- Base the read only on what the summary states. Never infer beyond it."""


def score_transcript_tone(state):
    return {
        "transcript_tone": score_document(
            state.get("transcript_doc"), SYSTEM_PROMPT, VALID_LABELS, LABEL_TO_DIRECTION
        )
    }
