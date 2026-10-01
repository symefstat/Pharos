-- ============================================================================
-- defense_space_articles
-- News feed for the "Defense & Space" tab — defense technology, dual-use systems,
-- aerospace, and space / satellites. Populated by home_news_run.py via the Toqan
-- Defense & Space Agent.
-- Same shape as the other feed tables; one table per Lodestar feed. See feeds.py.
-- ============================================================================

CREATE TABLE IF NOT EXISTS defense_space_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- defense-tech, dual-use, space, satellite, drone, procurement, …
    companies       TEXT[]      DEFAULT '{}',   -- defense / space firms named (Lockheed Martin, SpaceX, Anduril, …)
    business_impact TEXT,           -- material / contextual / none (stock materiality)
    scope           TEXT,           -- single-company / sector / regulatory / deal / comparison
    sentiment       TEXT,           -- business view of the company named: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE defense_space_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE defense_space_articles DROP CONSTRAINT IF EXISTS defense_space_articles_sentiment_check;
ALTER TABLE defense_space_articles ADD CONSTRAINT defense_space_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE defense_space_articles DROP CONSTRAINT IF EXISTS defense_space_articles_business_impact_check;
ALTER TABLE defense_space_articles ADD CONSTRAINT defense_space_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE defense_space_articles DROP CONSTRAINT IF EXISTS defense_space_articles_scope_check;
ALTER TABLE defense_space_articles ADD CONSTRAINT defense_space_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_defense_space_business_impact
    ON defense_space_articles (business_impact);
CREATE INDEX IF NOT EXISTS idx_defense_space_published_at
    ON defense_space_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_defense_space_fetched_at
    ON defense_space_articles (fetched_at DESC);

ALTER TABLE defense_space_articles DISABLE ROW LEVEL SECURITY;
