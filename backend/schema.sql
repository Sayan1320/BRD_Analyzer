-- schema.sql
-- Bootstrap script for the Requirement Summarizer AlloyDB schema.
-- Fully idempotent: safe to run multiple times against the same database.
-- Table creation order respects FK dependencies:
--   sessions → document_metadata → analysis_results → audit_logs

-- ─────────────────────────────────────────────
-- 1. sessions
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    filename         VARCHAR(255)  NOT NULL,
    file_size_bytes  BIGINT        NOT NULL,
    status           VARCHAR(20)   NOT NULL DEFAULT 'processing',
    page_count       INT,
    char_count       INT,
    result           JSONB,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- 2. document_metadata  (FK → sessions)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS document_metadata (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID         NOT NULL REFERENCES sessions(id),
    filename     VARCHAR(255) NOT NULL,
    file_type    VARCHAR(20),
    file_size_kb INT,
    page_count   INT,
    uploaded_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    status       VARCHAR(30)  NOT NULL DEFAULT 'processing'
);

-- ─────────────────────────────────────────────
-- 3. analysis_results  (FK → document_metadata, sessions)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analysis_results (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id         UUID         NOT NULL REFERENCES document_metadata(id),
    session_id          UUID         NOT NULL REFERENCES sessions(id),
    executive_summary   TEXT,
    user_stories        JSONB,
    acceptance_criteria JSONB,
    gap_flags           JSONB,
    model_used          VARCHAR(50),
    tokens_used         INT,
    processing_time_ms  INT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- 4. audit_logs  (FK → sessions)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID        NOT NULL REFERENCES sessions(id),
    event_type  VARCHAR(50) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_document_metadata_session_id  ON document_metadata(session_id);
CREATE INDEX IF NOT EXISTS idx_analysis_results_document_id  ON analysis_results(document_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_session_id         ON audit_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action             ON audit_logs(event_type);

-- ─────────────────────────────────────────────
-- Verification: should return 4
-- ─────────────────────────────────────────────
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name IN ('sessions', 'document_metadata', 'analysis_results', 'audit_logs');
