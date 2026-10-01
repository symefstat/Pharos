-- ============================================================================
-- watchlist
-- Items the user is tracking for alerts: a technology (key from technologies.py),
-- an entity (canonical name), or a feed (label). The scheduled alerts_run.py
-- checks these against recent material stories + technology stage transitions and
-- pushes a notification. Upserted on (kind, value).
-- ============================================================================

CREATE TABLE IF NOT EXISTS watchlist (
    id          BIGSERIAL   PRIMARY KEY,
    kind        TEXT        NOT NULL CHECK (kind IN ('technology', 'entity', 'feed')),
    value       TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (kind, value)
);

ALTER TABLE watchlist DISABLE ROW LEVEL SECURITY;
