-- Funding rounds per tracked technology — the first evidence signal that is
-- INDEPENDENT of news-headline classification. Stage placements derive from
-- headlines (a known, documented limitation); funding-round stage mix (seed/A/B
-- vs C+/growth/M&A/IPO) gives the dossier a second, independent read to
-- corroborate — or contradict — the news-derived lifecycle stage.
--
-- Populated by funding_run.py (CSV import today; a Dealroom/PitchBook API
-- client can slot into the same runner later). Display-only for now: the
-- corroboration read renders on the dossier; it does NOT enter the stage-call
-- algorithm until the mapping has earned trust.
CREATE TABLE IF NOT EXISTS funding_rounds (
    id            BIGSERIAL PRIMARY KEY,
    tech_key      TEXT NOT NULL,               -- technologies.py registry key
    company       TEXT NOT NULL,
    -- normalized by funding_run.py: seed | series-a | series-b | series-c-plus
    -- | growth | ipo | m&a | grant | debt | other
    round_type    TEXT NOT NULL,
    amount_usd    DOUBLE PRECISION,            -- NULL = undisclosed, never zero
    announced_on  DATE NOT NULL,
    investors     TEXT[],                      -- optional
    source        TEXT NOT NULL,               -- 'csv:<file>' | 'dealroom' | 'manual'
    source_url    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- idempotent re-imports: the same company/round/date upserts, never duplicates
    UNIQUE (tech_key, company, round_type, announced_on)
);

CREATE INDEX IF NOT EXISTS idx_funding_rounds_tech
    ON funding_rounds (tech_key, announced_on DESC);
