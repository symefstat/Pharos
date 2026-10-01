-- ============================================================================
-- prosus_companies
-- Reference table for the Prosus group portfolio — the entity list behind the
-- Prosus page's portfolio-company lens. Seeded/updated by prosus_seed.py;
-- read by home_news/writer.py (write-time tagging of feed articles) and by
-- prosus_backfill.py (one-off tagging of historical rows).
--
--   slug     — stable identifier; this is the value stored in the feed tables'
--              prosus_tags[] column (migrations/2026-07-03_prosus_tags.sql).
--   aliases  — the matching surface: names/brands that identify the company in
--              article text ("Just Eat", "Lieferando", "Codecademy", …).
--              EMPTY means "never auto-match" — used for companies whose name
--              is too ambiguous for text matching (Rain, Honor, Ema, Oda, …);
--              they stay in the table for display/reference but are only ever
--              tagged manually.
--   segment  — the six Prosus-page segments, plus 'internet' for Tencent
--              (shown as the NAV anchor rather than under a segment tab) and
--              'frontier-tech' for the Prosus Ventures deep-tech layer
--              (quantum, AI, robotics, bio, space, cyber).
--   tier     — 'core' (controlled / major stakes, first-class on the Prosus
--              page) vs 'ventures' (minority Prosus Ventures positions).
--   regions  — where the company operates, in Prosus-lens vocabulary (see
--              prosus/regions.py; 'latam' / 'india' / 'europe' are the three
--              strategic lenses surfaced in the UI).
--
-- Idempotent; safe to re-run.
-- ============================================================================

CREATE TABLE IF NOT EXISTS prosus_companies (
    slug        TEXT PRIMARY KEY,
    name        TEXT        NOT NULL,
    aliases     TEXT[]      NOT NULL DEFAULT '{}',
    segment     TEXT        NOT NULL,
    tier        TEXT        NOT NULL,
    regions     TEXT[]      NOT NULL DEFAULT '{}',
    ownership   TEXT,               -- freeform: '100%', 'majority', '~26%', 'minority (listed)'
    status      TEXT        NOT NULL DEFAULT 'active',   -- active / exited
    notes       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE prosus_companies DROP CONSTRAINT IF EXISTS prosus_companies_segment_check;
ALTER TABLE prosus_companies ADD CONSTRAINT prosus_companies_segment_check
    CHECK (segment IN ('food-delivery', 'payments-fintech', 'classifieds',
                       'edtech', 'ecommerce-travel', 'mobility', 'internet',
                       'frontier-tech'));

ALTER TABLE prosus_companies DROP CONSTRAINT IF EXISTS prosus_companies_tier_check;
ALTER TABLE prosus_companies ADD CONSTRAINT prosus_companies_tier_check
    CHECK (tier IN ('core', 'ventures'));

ALTER TABLE prosus_companies DROP CONSTRAINT IF EXISTS prosus_companies_status_check;
ALTER TABLE prosus_companies ADD CONSTRAINT prosus_companies_status_check
    CHECK (status IN ('active', 'exited'));

CREATE INDEX IF NOT EXISTS idx_prosus_companies_segment
    ON prosus_companies (segment);
CREATE INDEX IF NOT EXISTS idx_prosus_companies_tier
    ON prosus_companies (tier);

ALTER TABLE prosus_companies DISABLE ROW LEVEL SECURITY;
