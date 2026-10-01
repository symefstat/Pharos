-- ============================================================================
-- falsifier_events
-- Candidate evidence that a Strategist falsifier may have triggered — the
-- flagship "we told you what would prove us wrong, and we'll tell you when it
-- happens" loop. Each row links an OPEN manual forecast (predictions.id) to a
-- news article whose content matches the forecast's falsifier text.
--
-- Written by falsifier_run.py (every 6h, after alerts_run.py). Rows are
-- CANDIDATES only: detection never auto-resolves a forecast — grading stays
-- human (POST /api/forecasts/resolve), so the public record can't be corrupted
-- by a fuzzy text match. UNIQUE(pred_id, article_url) makes re-runs idempotent:
-- the same article can never re-alert for the same forecast.
-- ============================================================================

CREATE TABLE IF NOT EXISTS falsifier_events (
    id            BIGSERIAL   PRIMARY KEY,
    pred_id       BIGINT      NOT NULL REFERENCES predictions (id) ON DELETE CASCADE,
    falsifier     TEXT        NOT NULL,   -- the falsifier text as matched (snapshot, not a join)
    article_url   TEXT        NOT NULL,
    article_title TEXT,
    published_at  DATE,
    score         DOUBLE PRECISION,       -- vector cosine similarity, or keyword-overlap fraction
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (pred_id, article_url)
);

CREATE INDEX IF NOT EXISTS falsifier_events_detected_idx ON falsifier_events (detected_at DESC);
CREATE INDEX IF NOT EXISTS falsifier_events_pred_idx ON falsifier_events (pred_id);

ALTER TABLE falsifier_events DISABLE ROW LEVEL SECURITY;
