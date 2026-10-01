-- ============================================================================
-- prosus_portfolio_articles
-- News feed for the "Prosus" tab — Prosus group companies, their direct
-- competitors, and regulation in their core markets. Populated by
-- home_news_run.py via the Toqan Prosus Portfolio Agent.
-- Same shape as the other feed tables; one table per Lodestar feed. See feeds.py.
--
-- Unlike the older feed tables, prosus_tags is part of the initial schema
-- (elsewhere it arrives via migrations/2026-07-03_prosus_tags.sql).
-- ============================================================================

CREATE TABLE IF NOT EXISTS prosus_portfolio_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- earnings, competitor-move, regulation, …
    companies       TEXT[]      DEFAULT '{}',   -- companies named (iFood, Meituan, PayU, …)
    business_impact TEXT,           -- material / contextual / none (materiality for Prosus)
    scope           TEXT,           -- single-company / deal / sector / regulatory / comparison
    sentiment       TEXT,           -- viewed from the Prosus-relevant company: positive / negative / neutral
    prosus_tags     TEXT[]      NOT NULL DEFAULT '{}',  -- prosus_companies slugs (prosus/matcher.py)
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE prosus_portfolio_articles DROP CONSTRAINT IF EXISTS prosus_portfolio_articles_sentiment_check;
ALTER TABLE prosus_portfolio_articles ADD CONSTRAINT prosus_portfolio_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE prosus_portfolio_articles DROP CONSTRAINT IF EXISTS prosus_portfolio_articles_business_impact_check;
ALTER TABLE prosus_portfolio_articles ADD CONSTRAINT prosus_portfolio_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE prosus_portfolio_articles DROP CONSTRAINT IF EXISTS prosus_portfolio_articles_scope_check;
ALTER TABLE prosus_portfolio_articles ADD CONSTRAINT prosus_portfolio_articles_scope_check
    CHECK (scope IN ('single-company', 'deal', 'sector', 'regulatory', 'comparison'));

CREATE INDEX IF NOT EXISTS idx_prosus_portfolio_business_impact
    ON prosus_portfolio_articles (business_impact);
CREATE INDEX IF NOT EXISTS idx_prosus_portfolio_published_at
    ON prosus_portfolio_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_prosus_portfolio_fetched_at
    ON prosus_portfolio_articles (fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_prosus_portfolio_prosus_tags
    ON prosus_portfolio_articles USING GIN (prosus_tags);

ALTER TABLE prosus_portfolio_articles DISABLE ROW LEVEL SECURITY;
