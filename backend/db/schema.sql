-- Postgres schema for this project, assembled from three sources:
--   1. The Fundamental Analysis Subgraph specification's own "Database Schema"
--      section (financial_statements, analyst_price_targets,
--      analyst_rating_changes, fundamental_analysis_results) -- transcribed
--      verbatim, cross-checked against a real pg_dump of a working instance
--      of this schema (confirms analyst_rating_changes.analyst_firm is
--      NOT NULL, which the prose DDL omits but the primary key requires).
--   2. The Orchestrator Subgraph specification's "Database Schema" section
--      (orchestrator_runs) -- transcribed verbatim.
--   3. The Chat Intent & Routing Subgraph specification's "Database Schema"
--      section (conversation_sessions, conversation_messages) -- transcribed
--      verbatim.
--
-- Two tables are NOT from any specification document -- they are inferred
-- directly from existing code that queries them, since no document defines
-- them. Each is marked below with exactly what code depends on it and why.
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
-- conversation_sessions / conversation_messages -- Chat Intent & Routing
-- Subgraph spec. Not used by this repo's current chat_intent_routing/graph.py
-- (a temporary bridge -- see that file's docstring) since the real
-- parse_and_route node these tables support has not been built yet. Created
-- now so the schema is ready when it is.
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id  UUID PRIMARY KEY,
    last_ticker VARCHAR(20),
    last_horizon VARCHAR(10),
    last_scope  JSONB, -- e.g. ["technical", "fundamental"]
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- Optional, for audit/debugging conversation flow rather than resolution logic.
CREATE TABLE IF NOT EXISTS conversation_messages (
    session_id  UUID NOT NULL REFERENCES conversation_sessions(session_id),
    turn_index  INTEGER NOT NULL,
    role        VARCHAR(10) CHECK (role IN ('user', 'assistant')),
    content     TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (session_id, turn_index)
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

-- ============================================================================
-- "Memory".user_memory -- NOT from any specification document shared so far
-- (referenced only as "the already-created 'Memory'.user_memory table" by
-- a "User Memory -- Specification (Chat Intent & Routing Subgraph
-- Extension)" document that has not been shared with this repo). Inferred
-- from backend/agents/chat_intent_routing/nodes/load_user_memory.py and
-- update_user_memory.py, which is the only code that reads/writes it.
-- Confirm against that extension document once available.
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS "Memory";

CREATE TABLE IF NOT EXISTS "Memory".user_memory (
    user_id      VARCHAR(64) PRIMARY KEY,
    watchlist    JSONB,
    preferences  JSONB,
    updated_at   TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- "Memory".conversation_history -- append-only per-user turn log. Needed by
-- agents/chat_intent_routing/nodes/persist_conversation_turn.py (writes) and
-- nodes/load_conversation_history.py (reads, ordered by created_at per
-- user_id) -- Sourabh Shetti's implementation of the Chat Intent & Routing
-- subgraph. Inferred from those two node files, which are the only code
-- that reads/writes it; not from any specification document shared with
-- this repo.
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
