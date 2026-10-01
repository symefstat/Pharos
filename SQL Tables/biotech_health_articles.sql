-- ============================================================================
-- biotech_health_articles
-- News feed for the "Biotech & Health" tab — biotech / healthcare developments
-- that move markets (approvals, trials, gene editing, AI drug discovery, …).
-- Populated by home_news_run.py via the Toqan Biotech & Health Agent.
-- Same shape as home_news_articles; one table per Bellwether feed. See feeds.py.
-- ============================================================================

CREATE TABLE IF NOT EXISTS biotech_health_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- approval, trial, gene-editing, ai-drug-discovery, m&a, …
    companies       TEXT[]      DEFAULT '{}',   -- biotech / pharma firms named
    business_impact TEXT,           -- material / contextual / none (stock materiality)
    scope           TEXT,           -- single-company / sector / regulatory / deal / comparison
    sentiment       TEXT,           -- business view of the company named: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE biotech_health_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE biotech_health_articles DROP CONSTRAINT IF EXISTS biotech_health_articles_sentiment_check;
ALTER TABLE biotech_health_articles ADD CONSTRAINT biotech_health_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE biotech_health_articles DROP CONSTRAINT IF EXISTS biotech_health_articles_business_impact_check;
ALTER TABLE biotech_health_articles ADD CONSTRAINT biotech_health_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE biotech_health_articles DROP CONSTRAINT IF EXISTS biotech_health_articles_scope_check;
ALTER TABLE biotech_health_articles ADD CONSTRAINT biotech_health_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_biotech_health_business_impact
    ON biotech_health_articles (business_impact);
CREATE INDEX IF NOT EXISTS idx_biotech_health_published_at
    ON biotech_health_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_biotech_health_fetched_at
    ON biotech_health_articles (fetched_at DESC);

ALTER TABLE biotech_health_articles DISABLE ROW LEVEL SECURITY;
