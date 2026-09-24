-- Postgres schema for this project, assembled from two sources:
--   1. The Fundamental Analysis Subgraph specification's own "Database Schema"
--      section (financial_statements, analyst_price_targets,
--      analyst_rating_changes, fundamental_analysis_results) -- transcribed
--      verbatim, cross-checked against a real pg_dump of a working instance
--      of this schema (confirms analyst_rating_changes.analyst_firm is
--      NOT NULL, which the prose DDL omits but the primary key requires).
--   2. The Orchestrator Subgraph specification's "Database Schema" section
--      (orchestrator_runs) -- transcribed verbatim.
--
-- The remaining tables are NOT from any specification document -- they are
-- inferred directly from the code that uses them. Each is marked below with
-- exactly what code depends on it and why.
--
-- Run with:  psql "$DATABASE_URL" -f backend/db/schema.sql
-- (or set DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD and use `psql -h ... -f ...`)

-- ============================================================================
-- universe -- ticker metadata. Referenced (via FK) by every table in the
-- Fundamental Analysis specification's schema, but that specification never
-- defines it ("Reuses `universe` (ticker metadata)"). Base columns are
-- transcribed from a real pg_dump of a working instance of this project's
-- database, except `ticker`'s width: the dump had VARCHAR(10), which is too
-- narrow for NSE-suffixed Indian tickers (e.g. "ICICIBANK.NS" is 12
-- characters) that this project's own seeding scripts insert. Widened to
-- VARCHAR(20) to match the width the Orchestrator specification's own
-- orchestrator_runs.ticker column already uses.
-- ============================================================================
-- `active` is not in that pg_dump either -- it is required by
-- backend/agents/technical_analysis/nodes/fetch_price_history.py, whose
-- universe lookup reads "WHERE ticker = %s AND active". The separate ALTER
-- below covers databases created before this column was added here, since
-- CREATE TABLE IF NOT EXISTS leaves an existing table untouched.
CREATE TABLE IF NOT EXISTS universe (
    ticker       VARCHAR(20) PRIMARY KEY,
    company_name VARCHAR(255),
    exchange     VARCHAR(20),
    sector       VARCHAR(100),
    active       BOOLEAN DEFAULT TRUE
);
ALTER TABLE universe ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE;

-- ============================================================================
-- financial_statements -- source-of-truth for compute_growth,
-- compute_financial_health, and compute_relative_valuation. One row per
-- ticker + reporting period + period_type. Fundamental Analysis Subgraph spec.
-- ============================================================================
CREATE TABLE IF NOT EXISTS financial_statements (
    ticker                VARCHAR(20) NOT NULL REFERENCES universe(ticker),
    period_end_date       DATE NOT NULL,
    period_type           VARCHAR(10) NOT NULL CHECK (period_type IN ('annual', 'quarterly')),
    revenue               NUMERIC(18, 2),
    gross_profit          NUMERIC(18, 2),
    operating_profit      NUMERIC(18, 2),
    net_profit            NUMERIC(18, 2),
    eps                   NUMERIC(10, 4),
    total_debt            NUMERIC(18, 2),
    total_equity          NUMERIC(18, 2),
    cash_flow_operations  NUMERIC(18, 2), -- CFO -- used by compute_financial_health's cash flow quality check
    inventory             NUMERIC(18, 2),
    receivables           NUMERIC(18, 2),
    shares_outstanding    BIGINT,
    PRIMARY KEY (ticker, period_end_date, period_type)
);
CREATE INDEX IF NOT EXISTS idx_fs_ticker_period ON financial_statements (ticker, period_end_date DESC);

-- ============================================================================
-- analyst_price_targets -- periodic snapshot feeding compute_analyst_consensus.
-- Fundamental Analysis Subgraph spec.
-- ============================================================================
CREATE TABLE IF NOT EXISTS analyst_price_targets (
    ticker            VARCHAR(20) NOT NULL REFERENCES universe(ticker),
    as_of_date        DATE NOT NULL,
    avg_price_target  NUMERIC(12, 4),
    num_analysts      INT,
    PRIMARY KEY (ticker, as_of_date)
);

-- ============================================================================
-- analyst_rating_changes -- individual rating-change events, used for the
-- "net upgrades vs. downgrades" trend in compute_analyst_consensus.
-- Fundamental Analysis Subgraph spec. `analyst_firm` is NOT NULL here (the
-- specification's prose DDL omits that constraint, but it must hold since
-- the column is part of the primary key -- confirmed against a real
-- pg_dump of a working instance of this schema).
-- ============================================================================
CREATE TABLE IF NOT EXISTS analyst_rating_changes (
    ticker        VARCHAR(20) NOT NULL REFERENCES universe(ticker),
    action_date   DATE NOT NULL,
    analyst_firm  VARCHAR(60) NOT NULL,
    action        VARCHAR(20) CHECK (action IN ('upgrade', 'downgrade', 'initiate', 'maintain')),
    from_rating   VARCHAR(20),
    to_rating     VARCHAR(20),
    PRIMARY KEY (ticker, action_date, analyst_firm)
);
CREATE INDEX IF NOT EXISTS idx_arc_ticker_date ON analyst_rating_changes (ticker, action_date DESC);

-- ============================================================================
-- fundamental_analysis_results -- one row per ticker + as_of_date, the
-- cached output backend/agents/fundamental_analysis/nodes/persist_results.py
-- writes. Fundamental Analysis Subgraph spec.
-- ============================================================================
CREATE TABLE IF NOT EXISTS fundamental_analysis_results (
    ticker                      VARCHAR(20) NOT NULL REFERENCES universe(ticker),
    as_of_date                  DATE NOT NULL,
    data_tier                   VARCHAR(15) CHECK (data_tier IN ('full', 'medium', 'limited', 'insufficient')),
    relative_valuation_class    VARCHAR(15), -- 'cheap' | 'fair' | 'expensive'
    relative_valuation_detail   JSONB,
    growth_class                VARCHAR(15), -- 'accelerating' | 'stable' | 'decelerating'
    growth_detail               JSONB,
    financial_health_class      VARCHAR(10), -- 'strong' | 'stable' | 'weak'
    financial_health_detail     JSONB,
    analyst_consensus_class     VARCHAR(10), -- 'bullish' | 'neutral' | 'bearish'
    analyst_consensus_detail    JSONB,
    composite_direction         VARCHAR(10) CHECK (composite_direction IN ('bullish', 'bearish', 'neutral')),
    composite_confidence        NUMERIC(5, 2),
    risk_flags                  JSONB,
    created_at                  TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ticker, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_far_ticker_date ON fundamental_analysis_results (ticker, as_of_date DESC);

-- ============================================================================
-- orchestrator_runs -- optional run-level audit table. Orchestrator Subgraph
-- spec ("Recommended optional table"). Written by
-- backend/agents/orchestrator/nodes/persist_run.py on every run, including
-- the invalid-input path. Three columns below (requires_review,
-- reviewer_decision, review_notes) are NOT in the specification's DDL --
-- added because persist_run.py's own record already computes them, and
-- dropping them would silently discard data that code produces.
-- ============================================================================
CREATE TABLE IF NOT EXISTS orchestrator_runs (
    run_id             UUID PRIMARY KEY,
    ticker             VARCHAR(20) NOT NULL,
    analysis_horizon   VARCHAR(50) NOT NULL,
    technical_status   VARCHAR(20),
    fundamental_status VARCHAR(20),
    sentiment_status   VARCHAR(20),
    selected_tool      VARCHAR(50),
    tool_loop_count    INTEGER DEFAULT 0,
    final_decision     VARCHAR(50),
    final_response     JSONB,
    error_details      JSONB,
    requires_review    BOOLEAN,
    reviewer_decision  VARCHAR(20),
    review_notes       TEXT,
    created_at         TIMESTAMP DEFAULT NOW(),
    updated_at         TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- "Technical".price_history -- NOT from any specification document shared
-- so far. Inferred from existing code that queries it:
--   - backend/agents/orchestrator/nodes/_current_price.py reads the latest
--     close_price here to supply Fundamental Analysis's current_price input.
--   - The original (pre-yfinance) backend/agents/technical_analysis/nodes/
--     fetch_price_history.py read full OHLCV bars from here.
-- Column list matches that original fetch_price_history.py's PRICE_COLUMNS.
-- Confirm this against the real Technical Analysis Subgraph specification's
-- own Database Schema section once available -- this repo has not been
-- shown that document.
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS "Technical";

CREATE TABLE IF NOT EXISTS "Technical".price_history (
    ticker          VARCHAR(20) NOT NULL REFERENCES universe(ticker),
    trade_date      DATE NOT NULL,
    open_price      NUMERIC(18, 4),
    high_price      NUMERIC(18, 4),
    low_price       NUMERIC(18, 4),
    close_price     NUMERIC(18, 4),
    adjusted_close  NUMERIC(18, 4),
    volume          BIGINT,
    PRIMARY KEY (ticker, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_price_history_ticker_date ON "Technical".price_history (ticker, trade_date DESC);

-- ============================================================================
-- "Technical".technical_analysis_results -- cached per-ticker/per-day output,
-- written by backend/agents/technical_analysis/nodes/persist_results.py (see
-- db/upsert.py's save_technical_analysis_results). Like price_history above,
-- NOT from any specification document shared so far: every column below is
-- taken directly from the `record` dict persist_results.py already builds, so
-- the two stay in step. Confirm against the real Technical Analysis Subgraph
-- specification's Database Schema section once available.
-- ============================================================================
CREATE TABLE IF NOT EXISTS "Technical".technical_analysis_results (
    ticker               VARCHAR(20) NOT NULL REFERENCES universe(ticker),
    analysis_date        DATE NOT NULL,
    trend                VARCHAR(20),
    momentum             VARCHAR(20),
    volatility           VARCHAR(20),
    support_level        NUMERIC(18, 4),
    resistance_level     NUMERIC(18, 4),
    overall_direction    VARCHAR(10),
    confidence_score     NUMERIC(5, 2),
    candlestick_pattern  VARCHAR(50),
    pattern_direction    VARCHAR(10),
    volume_confirmed     BOOLEAN,
    trend_aligned        BOOLEAN,
    entry_price          NUMERIC(18, 4),
    stop_loss            NUMERIC(18, 4),
    target_price         NUMERIC(18, 4),
    risk_reward_ratio    NUMERIC(6, 2),
    trade_status         VARCHAR(20),
    technical_summary    JSONB,
    created_at           TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (ticker, analysis_date)
);
CREATE INDEX IF NOT EXISTS idx_tar_ticker_date
    ON "Technical".technical_analysis_results (ticker, analysis_date DESC);

CREATE SCHEMA IF NOT EXISTS "Memory";

-- ============================================================================
-- "Memory".conversation_history -- append-only per-user turn log, written by
-- agents/chat_intent_routing/nodes/persist_conversation_turn.py. Nothing
-- reads it back yet; it serves as an audit trail.
-- ============================================================================
CREATE TABLE IF NOT EXISTS "Memory".conversation_history (
    turn_id          UUID PRIMARY KEY,
    user_id          VARCHAR(64) NOT NULL,
    thread_id        VARCHAR(64),
    message          TEXT,
    intent           VARCHAR(20),
    resolved_ticker  VARCHAR(20),
    response         JSONB,
    created_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conversation_history_user_created
    ON "Memory".conversation_history (user_id, created_at DESC);

-- ============================================================================
-- document_summaries -- one row per filing PDF that backend/jobs/
-- summarise_reports.py has downloaded, read and summarised. Not from any
-- specification document: it is defined by that job, which is the only code
-- that writes it.
--
-- report_type is the abbreviation the job stores:
--     AR  annual report
--     TR  transcript report (earnings or AGM call)
-- CHECK-constrained rather than free text so a typo fails at write time
-- instead of quietly creating a third category nobody queries for.
--
-- Keyed on sha256 of the PDF bytes rather than on (ticker, date). Identical
-- bytes mean the identical document whichever feed served it, and BSE does
-- serve the same report twice under different attachment ids -- that is what
-- makes the job safe to re-run without accumulating duplicates.
--
-- Deliberately no FK to universe(ticker). This job addresses companies by BSE
-- scrip code and covers the top 20 by market capitalisation, which is not the
-- same set as universe, and whose tickers here are unsuffixed ("INFY") where
-- universe holds NSE-suffixed ones ("INFY.NS"). An FK would reject rows for
-- companies the rest of the pipeline has not seeded yet.
-- ============================================================================
CREATE TABLE IF NOT EXISTS document_summaries (
    id            BIGSERIAL PRIMARY KEY,
    scrip_code    VARCHAR(20) NOT NULL,   -- BSE numeric code, the stable key
    ticker        VARCHAR(20),
    company_name  VARCHAR(255),
    report_name   TEXT NOT NULL,          -- the document's title as filed
    report_type   VARCHAR(2) NOT NULL CHECK (report_type IN ('AR', 'TR')),
    filed_on      DATE,
    source        VARCHAR(20),            -- 'bse' | 'company_site'
    source_url    TEXT,
    local_path    TEXT,
    sha256        CHAR(64) NOT NULL UNIQUE,
    page_count    INTEGER,                -- what the model was actually given:
    char_count    INTEGER,                -- a 200-page report reduced from 1.2M
                                          -- characters is a different artefact
                                          -- from one built on 40,000
    summary       TEXT NOT NULL,
    model         VARCHAR(60),
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);
-- The query the analysis agents will run: latest AR or TR for one company.
CREATE INDEX IF NOT EXISTS idx_document_summaries_lookup
    ON document_summaries (scrip_code, report_type, filed_on DESC);
CREATE INDEX IF NOT EXISTS idx_document_summaries_ticker
    ON document_summaries (ticker);

-- Sentiment scoring cache. agents/sentiment_analysis scores a summary once
-- with the LLM and stores the verdict back on the row, so a later request for
-- the same document is served from here instead of paying for the call again
-- (see db/upsert.py's save_document_sentiment, and _score_helpers.py's
-- "cached"/"scored" source field). Separate ALTERs rather than columns in the
-- CREATE TABLE above: document_summaries predates this, and
-- CREATE TABLE IF NOT EXISTS leaves an existing table untouched.
ALTER TABLE document_summaries ADD COLUMN IF NOT EXISTS sentiment_label      VARCHAR(20);
ALTER TABLE document_summaries ADD COLUMN IF NOT EXISTS sentiment_rationale  TEXT;
ALTER TABLE document_summaries ADD COLUMN IF NOT EXISTS sentiment_model      VARCHAR(60);
ALTER TABLE document_summaries ADD COLUMN IF NOT EXISTS sentiment_scored_at  TIMESTAMP;

-- The agents look documents up by unsuffixed BSE ticker, not scrip_code (see
-- agents/sentiment_analysis/nodes/_fetch_helpers.py) -- the lookup index above
-- is keyed on scrip_code and cannot serve that.
CREATE INDEX IF NOT EXISTS idx_document_summaries_ticker_lookup
    ON document_summaries (ticker, report_type, filed_on DESC);
