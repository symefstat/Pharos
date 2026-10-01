-- ============================================================================
-- geopolitics_trade_articles
-- News feed for the "Geopolitics & Trade" tab — economic statecraft that moves
-- markets (tariffs, sanctions, export controls, critical minerals, …).
-- Populated by home_news_run.py via the Toqan Geopolitics & Trade Agent.
-- Same shape as home_news_articles; one table per Bellwether feed. See feeds.py.
-- ============================================================================

CREATE TABLE IF NOT EXISTS geopolitics_trade_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- tariff, export-controls, sanctions, critical-minerals, …
    companies       TEXT[]      DEFAULT '{}',   -- firms materially affected (often empty)
    business_impact TEXT,           -- material / contextual / none (stock materiality)
    scope           TEXT,           -- single-company / sector / regulatory / deal / comparison
    sentiment       TEXT,           -- business view of the exposed sector/firms: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE geopolitics_trade_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE geopolitics_trade_articles DROP CONSTRAINT IF EXISTS geopolitics_trade_articles_sentiment_check;
ALTER TABLE geopolitics_trade_articles ADD CONSTRAINT geopolitics_trade_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE geopolitics_trade_articles DROP CONSTRAINT IF EXISTS geopolitics_trade_articles_business_impact_check;
ALTER TABLE geopolitics_trade_articles ADD CONSTRAINT geopolitics_trade_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE geopolitics_trade_articles DROP CONSTRAINT IF EXISTS geopolitics_trade_articles_scope_check;
ALTER TABLE geopolitics_trade_articles ADD CONSTRAINT geopolitics_trade_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_geopolitics_trade_business_impact
    ON geopolitics_trade_articles (business_impact);
CREATE INDEX IF NOT EXISTS idx_geopolitics_trade_published_at
    ON geopolitics_trade_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_geopolitics_trade_fetched_at
    ON geopolitics_trade_articles (fetched_at DESC);

ALTER TABLE geopolitics_trade_articles DISABLE ROW LEVEL SECURITY;
