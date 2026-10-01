-- ============================================================================
-- technology_stage_history
-- Never-pruned daily snapshot of where each tracked technology (technologies.py)
-- sits on its lifecycle — the modal MOT-lens stage of the articles that map to
-- it. Maintained by analytics/tech_layer.py (TechAnalyst.snapshot), upserted on
-- (technology, as_of). Diffing consecutive snapshots yields the decisive event:
-- a stage transition (emerging→growth, early-adopters→early-majority).
-- ============================================================================

CREATE TABLE IF NOT EXISTS technology_stage_history (
    technology     TEXT        NOT NULL,   -- key from technologies.py
    as_of          DATE        NOT NULL,
    label          TEXT,
    domain         TEXT,
    maturity_stage TEXT,                   -- modal S-curve stage that day
    adoption_stage TEXT,                   -- modal diffusion stage that day
    strategic_move TEXT,                   -- dominant strategic move
    article_count  INTEGER     NOT NULL DEFAULT 0,
    entrant_count  INTEGER     NOT NULL DEFAULT 0,  -- distinct companies (ferment proxy)
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (technology, as_of)
);

CREATE INDEX IF NOT EXISTS idx_tech_stage_history_tech
    ON technology_stage_history (technology, as_of DESC);

ALTER TABLE technology_stage_history DISABLE ROW LEVEL SECURITY;
