-- Schema for the document summarisation job (backend/jobs/summarise_reports.py).
--
-- Only one table is defined here, and it is the only one this work adds. The
-- agent packages under backend/agents/ expect tables of their own via
-- db.upsert.save_fundamental_analysis_results and
-- save_technical_analysis_results; those are not defined here because their
-- shape belongs to whoever wrote those agents. Adding guesses would be worse
-- than leaving the gap visible.
--
-- Apply with:  python -m db.apply_schema        (from backend/)

CREATE TABLE IF NOT EXISTS document_summaries (
    id              BIGSERIAL PRIMARY KEY,

    -- Who the document belongs to. scrip_code is BSE's numeric identifier and
    -- is the stable key; ticker and company_name are for humans reading rows.
    scrip_code      TEXT        NOT NULL,
    ticker          TEXT,
    company_name    TEXT,

    -- What the document is. report_type is the abbreviation the job writes:
    --   AR  annual report
    --   TR  transcript report (earnings or AGM call)
    -- Constrained rather than free text so a typo fails at write time instead
    -- of quietly creating a third category nobody queries for.
    report_name     TEXT        NOT NULL,
    report_type     TEXT        NOT NULL CHECK (report_type IN ('AR', 'TR')),
    filed_on        DATE,

    -- Where it came from, so any summary can be traced back to the filing it
    -- was derived from. sha256 is of the PDF bytes.
    source          TEXT,
    source_url      TEXT,
    local_path      TEXT,
    sha256          CHAR(64)    NOT NULL,

    -- What was fed to the model, so a summary can be judged in context: a
    -- 200-page report reduced from 1.2 million characters is a different
    -- artefact from one built on 40,000.
    page_count      INTEGER,
    char_count      INTEGER,

    summary         TEXT        NOT NULL,
    model           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- The same PDF summarised twice is one row, updated. Identical bytes mean
    -- the identical document, whichever feed or company site served it, so
    -- this is what makes the job safe to re-run.
    CONSTRAINT document_summaries_sha256_key UNIQUE (sha256)
);

-- The query the analysis agents will actually run: latest AR or TR for a company.
CREATE INDEX IF NOT EXISTS document_summaries_lookup_idx
    ON document_summaries (scrip_code, report_type, filed_on DESC);

CREATE INDEX IF NOT EXISTS document_summaries_ticker_idx
    ON document_summaries (ticker);
