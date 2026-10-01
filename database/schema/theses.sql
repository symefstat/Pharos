-- ============================================================================
-- theses + thesis_events
-- The investor's PRIVATE thesis book — "thesis maintenance" automated.
--
-- A thesis is an investment belief registered with the evidence that would
-- FALSIFY it (required) and, optionally, the evidence that would CONFIRM it.
-- Theses deliberately live in their own table, NOT in `predictions`: they must
-- never contaminate the public ledger, the track record, or the calibration
-- stats. They only reuse the falsifier-watch detection engine
-- (analytics.thesis_watch, run by falsifier_run.py).
--
-- thesis_events mirrors falsifier_events: each row links a thesis to a news
-- article whose content matches its falsifier or confirmer text, labeled
-- 'falsifies' or 'confirms'. Rows are CANDIDATES only — nothing here changes a
-- thesis; the admin reviews the evidence in Track record.
-- UNIQUE(thesis_id, article_url) makes re-runs idempotent: the same article
-- can never re-alert for the same thesis.
-- ============================================================================

CREATE TABLE IF NOT EXISTS theses (
    id          BIGSERIAL   PRIMARY KEY,
    claim       TEXT        NOT NULL,      -- the investment thesis itself
    falsifier   TEXT        NOT NULL,      -- evidence that would prove it wrong
    confirmer   TEXT,                      -- evidence that would confirm it (optional)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived    BOOLEAN     NOT NULL DEFAULT FALSE   -- soft delete; events are kept
);

CREATE INDEX IF NOT EXISTS theses_active_idx ON theses (created_at DESC) WHERE NOT archived;

CREATE TABLE IF NOT EXISTS thesis_events (
    id            BIGSERIAL   PRIMARY KEY,
    thesis_id     BIGINT      NOT NULL REFERENCES theses (id) ON DELETE CASCADE,
    matched       TEXT        NOT NULL,   -- the falsifier|confirmer text as matched (snapshot)
    label         TEXT        NOT NULL CHECK (label IN ('falsifies', 'confirms')),
    article_url   TEXT        NOT NULL,
    article_title TEXT,
    published_at  DATE,
    score         DOUBLE PRECISION,       -- keyword-overlap fraction (0..1)
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (thesis_id, article_url)
);

CREATE INDEX IF NOT EXISTS thesis_events_detected_idx ON thesis_events (detected_at DESC);
CREATE INDEX IF NOT EXISTS thesis_events_thesis_idx ON thesis_events (thesis_id);

ALTER TABLE theses DISABLE ROW LEVEL SECURITY;
ALTER TABLE thesis_events DISABLE ROW LEVEL SECURITY;
