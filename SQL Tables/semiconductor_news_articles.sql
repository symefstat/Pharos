-- ============================================================================
-- semiconductor_news_articles
-- News feed for the "Chips" tab — the semiconductor / chip value chain.
-- Populated by home_news_run.py via the Toqan Semiconductor News Agent.
-- Same shape as home_news_articles; one table per Bellwether feed. See feeds.py.
-- ============================================================================

CREATE TABLE IF NOT EXISTS semiconductor_news_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- fab, foundry, node, ai-accelerator, export-controls, …
    companies       TEXT[]      DEFAULT '{}',   -- chip firms named (TSMC, Nvidia, ASML, …)
    business_impact TEXT,           -- material / contextual / none (stock materiality)
    scope           TEXT,           -- single-company / sector / regulatory / deal / comparison
    sentiment       TEXT,           -- business view of the company named: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE semiconductor_news_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE semiconductor_news_articles DROP CONSTRAINT IF EXISTS semiconductor_news_articles_sentiment_check;
ALTER TABLE semiconductor_news_articles ADD CONSTRAINT semiconductor_news_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE semiconductor_news_articles DROP CONSTRAINT IF EXISTS semiconductor_news_articles_business_impact_check;
ALTER TABLE semiconductor_news_articles ADD CONSTRAINT semiconductor_news_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE semiconductor_news_articles DROP CONSTRAINT IF EXISTS semiconductor_news_articles_scope_check;
ALTER TABLE semiconductor_news_articles ADD CONSTRAINT semiconductor_news_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_semiconductor_news_business_impact
    ON semiconductor_news_articles (business_impact);
CREATE INDEX IF NOT EXISTS idx_semiconductor_news_published_at
    ON semiconductor_news_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_semiconductor_news_fetched_at
    ON semiconductor_news_articles (fetched_at DESC);

ALTER TABLE semiconductor_news_articles DISABLE ROW LEVEL SECURITY;
