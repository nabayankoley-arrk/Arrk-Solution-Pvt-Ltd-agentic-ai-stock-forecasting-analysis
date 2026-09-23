"""fetch_transcript — data access node.

Retrieves the latest earnings/AGM call transcript already ingested by
jobs/summarise_reports.py (report_type "TR" in document_summaries) for
this ticker, within config.TRANSCRIPT_LOOKBACK_MONTHS. See
docs/fundamental-analysis-design.md-style module split: retrieval logic
itself lives in ._fetch_helpers, shared with fetch_annual_report.py.
"""

from ..config import TRANSCRIPT_LOOKBACK_MONTHS
from ._fetch_helpers import fetch_latest_document


def fetch_transcript(state):
    doc, status, error = fetch_latest_document(state.get("ticker"), "TR", TRANSCRIPT_LOOKBACK_MONTHS)
    return {
        "transcript_doc": doc,
        "pillar_status": {"transcript": status},
        "errors": {"transcript": error},
    }
