-- ============================================================================
-- climate_energy_articles
-- News feed for the "Climate & Energy" tab — clean-energy generation and
-- climate markets (solar, wind, grid, hydrogen, nuclear, storage, carbon, …).
-- EV and AI-data-center-energy stories live in their own tabs.
-- Populated by home_news_run.py via the Toqan Climate & Clean Energy Agent.
-- Same shape as home_news_articles; one table per Bellwether feed. See feeds.py.
-- ============================================================================

CREATE TABLE IF NOT EXISTS climate_energy_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- solar, wind, grid, hydrogen, nuclear, storage, carbon-market, …
    companies       TEXT[]      DEFAULT '{}',   -- clean-energy firms / utilities named
    business_impact TEXT,           -- material / contextual / none (stock materiality)
    scope           TEXT,           -- single-company / sector / regulatory / deal / comparison
    sentiment       TEXT,           -- business view of the company/sector named: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE climate_energy_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE climate_energy_articles DROP CONSTRAINT IF EXISTS climate_energy_articles_sentiment_check;
ALTER TABLE climate_energy_articles ADD CONSTRAINT climate_energy_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE climate_energy_articles DROP CONSTRAINT IF EXISTS climate_energy_articles_business_impact_check;
ALTER TABLE climate_energy_articles ADD CONSTRAINT climate_energy_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE climate_energy_articles DROP CONSTRAINT IF EXISTS climate_energy_articles_scope_check;
ALTER TABLE climate_energy_articles ADD CONSTRAINT climate_energy_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_climate_energy_business_impact
    ON climate_energy_articles (business_impact);
CREATE INDEX IF NOT EXISTS idx_climate_energy_published_at
    ON climate_energy_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_climate_energy_fetched_at
    ON climate_energy_articles (fetched_at DESC);

ALTER TABLE climate_energy_articles DISABLE ROW LEVEL SECURITY;
