-- ============================================================================
-- fintech_articles
-- News feed for the "Fintech" tab — payments, banking infrastructure, lending,
-- and digital assets / crypto. Populated by home_news_run.py via the Toqan
-- Fintech & Digital Assets Agent.
-- Same shape as the other feed tables; one table per Lodestar feed. See feeds.py.
-- ============================================================================

CREATE TABLE IF NOT EXISTS fintech_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- payments, banking, lending, digital-assets, stablecoin, crypto, …
    companies       TEXT[]      DEFAULT '{}',   -- fintech / payment / crypto firms named (Visa, Stripe, Coinbase, …)
    business_impact TEXT,           -- material / contextual / none (stock materiality)
    scope           TEXT,           -- single-company / sector / regulatory / deal / comparison
    sentiment       TEXT,           -- business view of the company named: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE fintech_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE fintech_articles DROP CONSTRAINT IF EXISTS fintech_articles_sentiment_check;
ALTER TABLE fintech_articles ADD CONSTRAINT fintech_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE fintech_articles DROP CONSTRAINT IF EXISTS fintech_articles_business_impact_check;
ALTER TABLE fintech_articles ADD CONSTRAINT fintech_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE fintech_articles DROP CONSTRAINT IF EXISTS fintech_articles_scope_check;
ALTER TABLE fintech_articles ADD CONSTRAINT fintech_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_fintech_business_impact
    ON fintech_articles (business_impact);
CREATE INDEX IF NOT EXISTS idx_fintech_published_at
    ON fintech_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_fintech_fetched_at
    ON fintech_articles (fetched_at DESC);

ALTER TABLE fintech_articles DISABLE ROW LEVEL SECURITY;
