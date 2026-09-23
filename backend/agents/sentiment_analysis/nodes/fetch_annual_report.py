"""fetch_annual_report — data access node.

Retrieves the latest annual report already ingested by
jobs/summarise_reports.py (report_type "AR" in document_summaries) for
this ticker, within config.ANNUAL_REPORT_LOOKBACK_MONTHS. Stands in for
the specification's fetch_coverage_reports (see __init__.py for why).
Retrieval logic itself lives in ._fetch_helpers, shared with
fetch_transcript.py.
"""

from ..config import ANNUAL_REPORT_LOOKBACK_MONTHS
from ._fetch_helpers import fetch_latest_document


def fetch_annual_report(state):
    doc, status, error = fetch_latest_document(state.get("ticker"), "AR", ANNUAL_REPORT_LOOKBACK_MONTHS)
    return {
        "annual_report_doc": doc,
        "pillar_status": {"annual_report": status},
        "errors": {"annual_report": error},
    }
