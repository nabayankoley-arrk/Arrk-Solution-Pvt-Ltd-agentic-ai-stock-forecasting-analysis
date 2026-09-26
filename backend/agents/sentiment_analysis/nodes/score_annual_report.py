"""score_annual_report — the latest annual report's sentiment profile (see _score_helpers)."""

from ._score_helpers import score_document


def score_annual_report(state):
    return {"annual_report_score": score_document(state.get("annual_report_doc"), "AR")}
