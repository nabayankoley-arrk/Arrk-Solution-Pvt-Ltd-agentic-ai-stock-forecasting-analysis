"""Reads and writes for document_summaries.

Kept separate from db/upsert.py, which the agent packages import for their own
tables. Their file does not exist yet either, and putting unrelated functions
in it would make the eventual merge harder.
"""

from .connection import get_connection

# AR and TR are the abbreviations stored in report_type, and the schema has a
# CHECK constraint on exactly these two.
REPORT_TYPES = {
    "annual_report": "AR",
    "transcript": "TR",
}

_INSERT = """
    INSERT INTO document_summaries (
        scrip_code, ticker, company_name, report_name, report_type, filed_on,
        source, source_url, local_path, sha256, page_count, char_count,
        summary, model
    ) VALUES (
        %(scrip_code)s, %(ticker)s, %(company_name)s, %(report_name)s,
        %(report_type)s, %(filed_on)s, %(source)s, %(source_url)s,
        %(local_path)s, %(sha256)s, %(page_count)s, %(char_count)s,
        %(summary)s, %(model)s
    )
    ON CONFLICT (sha256) DO UPDATE SET
        scrip_code   = EXCLUDED.scrip_code,
        ticker       = EXCLUDED.ticker,
        company_name = EXCLUDED.company_name,
        report_name  = EXCLUDED.report_name,
        report_type  = EXCLUDED.report_type,
        filed_on     = EXCLUDED.filed_on,
        source       = EXCLUDED.source,
        source_url   = EXCLUDED.source_url,
        local_path   = EXCLUDED.local_path,
        page_count   = EXCLUDED.page_count,
        char_count   = EXCLUDED.char_count,
        summary      = EXCLUDED.summary,
        model        = EXCLUDED.model,
        updated_at   = now()
    RETURNING id, (xmax = 0) AS inserted
"""


def report_type_for(doc_types):
    """AR or TR for a document's classified types, or None if it is neither.

    Annual report wins when a document is both -- a combined report-and-AGM-
    notice PDF is filed as an annual report and that is how it should be stored.
    """
    for doc_type in ("annual_report", "transcript"):
        if doc_type in (doc_types or []):
            return REPORT_TYPES[doc_type]
    return None


def save_summary(record, connection=None):
    """Writes one summary, returning "inserted" or "updated".

    Keyed on the PDF's sha256, so re-running the job over the same documents
    refreshes rows rather than accumulating duplicates.
    """
    owned = connection is None
    connection = connection or get_connection()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(_INSERT, record)
            _, inserted = cursor.fetchone()
        return "inserted" if inserted else "updated"
    finally:
        if owned:
            connection.close()


def existing_checksums(connection=None):
    """Every sha256 already summarised, so a rerun can skip the model call.

    The expensive part of this job is the model, not the download, so knowing
    what has already been summarised is what makes a rerun cheap.
    """
    owned = connection is None
    connection = connection or get_connection()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT sha256 FROM document_summaries")
            return {row[0] for row in cursor.fetchall()}
    finally:
        if owned:
            connection.close()


def latest_for(scrip_code, report_type, connection=None):
    """The most recent stored summary of one type for one company, or None."""
    owned = connection is None
    connection = connection or get_connection()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT report_name, filed_on, summary, source_url, model, created_at
                FROM document_summaries
                WHERE scrip_code = %s AND report_type = %s
                ORDER BY filed_on DESC NULLS LAST, created_at DESC
                LIMIT 1
                """,
                (str(scrip_code), report_type),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        keys = ("report_name", "filed_on", "summary", "source_url", "model", "created_at")
        return dict(zip(keys, row))
    finally:
        if owned:
            connection.close()
