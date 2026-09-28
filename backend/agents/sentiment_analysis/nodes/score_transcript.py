"""score_transcript — the latest call transcript's sentiment profile (see _score_helpers)."""

from ._score_helpers import score_document


def score_transcript(state):
    return {"transcript_score": score_document(state.get("transcript_doc"), "TR")}
