-- ============================================================================
-- strategist_briefs
-- Cached theory-grounded Strategist read — one row per (as_of, focus). Generated
-- by analytics/strategist.py via the Toqan Strategist Agent and read instantly by
-- the 🧭 Strategist tab. Replaces the old executive_brief cache.
--   strategic_read — {markdown: ...} (or a structured object) — the read itself
--   stories        — the slim developments the read was built from (cited [S#])
--   theory         — the MOT passages retrieved + cited ([T#]) with source_file
-- Upserted on (as_of, focus).
-- ============================================================================

CREATE TABLE IF NOT EXISTS strategist_briefs (
    id             BIGSERIAL   PRIMARY KEY,
    as_of          DATE        NOT NULL,                 -- the day the read summarises
    focus          TEXT        NOT NULL DEFAULT 'daily', -- 'daily' or a chosen entity/feed/question
    strategic_read JSONB       NOT NULL,                 -- {markdown: ...} or structured
    stories        JSONB       NOT NULL DEFAULT '[]',    -- developments cited as [S#]
    theory         JSONB       NOT NULL DEFAULT '[]',    -- [{label, source_file, similarity, chunk_text}]
    window_days    INTEGER,                              -- look-back window used
    generated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (as_of, focus)
);

CREATE INDEX IF NOT EXISTS idx_strategist_briefs_focus_as_of
    ON strategist_briefs (focus, as_of DESC);

ALTER TABLE strategist_briefs DISABLE ROW LEVEL SECURITY;
