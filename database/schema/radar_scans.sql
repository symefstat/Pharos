-- Radar scan log — one row per scan (scheduled or directed), feeding the
-- Radar page's transparency strip: "last scan read N stories + M abstracts,
-- proposed P, surfaced S, rejected R". The rejected count is the trust
-- signal — it proves the evidence gate filters the agent for real.
-- Fail-open: analytics/radar.py works without this table (no strip shown).
CREATE TABLE IF NOT EXISTS radar_scans (
    id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    brief    TEXT,                    -- NULL = broad scan; else the analyst's question
    corpus   INTEGER NOT NULL,        -- unmatched news stories read
    papers   INTEGER NOT NULL,        -- arXiv abstracts read
    proposed INTEGER NOT NULL,        -- Scout proposals (post registry-dedupe)
    surfaced INTEGER NOT NULL,        -- passed the evidence gate and stored
    rejected INTEGER NOT NULL         -- failed the gate — never shown to users
);

CREATE INDEX IF NOT EXISTS idx_radar_scans_latest ON radar_scans (at DESC);
