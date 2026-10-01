-- ============================================================================
-- disruptive_tech_articles
-- News feed for the "Disruptive Tech" tab — frontier-tech breakthroughs and
-- market-structure moves that could change who wins in a market.
-- Populated by home_news_run.py via the Toqan Disruptive Tech Agent.
-- Same shape as home_news_articles; kept as a separate table per feed so the
-- topics stay cleanly organised. See feeds.py for the feed→table mapping.
-- ============================================================================

CREATE TABLE IF NOT EXISTS disruptive_tech_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- breakthrough, product-launch, funding, m&a, regulation, …
    companies       TEXT[]      DEFAULT '{}',   -- startups / incumbents / labs named
    -- Would an informed investor plausibly re-price a named public company's stock?
    --   'material'   = landmark round/IPO/M&A, market-reshaping regulation or
    --                  standards, commercialization milestone with revenue impact,
    --                  credible existential threat to an incumbent
    --   'contextual' = relevant backdrop, no direct re-pricing (early launch,
    --                  single research milestone, adoption/market report)
    --   'none'       = pure research / lab demo / early signal, no near-term
    --                  financial consequence
    business_impact TEXT,
    -- Why the article names the company/companies it does:
    --   'single-company' = one company is the subject
    --   'sector'         = industry-wide trend naming several players
    --   'regulatory'     = law / ruling / standards decision unlocking or killing a market
    --   'deal'           = M&A / stake / funding round / JV / partnership between named parties
    --   'comparison'     = ranking / head-to-head of products or players
    scope           TEXT,
    sentiment       TEXT,           -- competitive view of the company named: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- CHECK constraints on the controlled-vocabulary fields (added as named
-- constraints so the allowed sets can be widened idempotently later).
ALTER TABLE disruptive_tech_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE disruptive_tech_articles DROP CONSTRAINT IF EXISTS disruptive_tech_articles_sentiment_check;
ALTER TABLE disruptive_tech_articles ADD CONSTRAINT disruptive_tech_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE disruptive_tech_articles DROP CONSTRAINT IF EXISTS disruptive_tech_articles_business_impact_check;
ALTER TABLE disruptive_tech_articles ADD CONSTRAINT disruptive_tech_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE disruptive_tech_articles DROP CONSTRAINT IF EXISTS disruptive_tech_articles_scope_check;
ALTER TABLE disruptive_tech_articles ADD CONSTRAINT disruptive_tech_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_disruptive_tech_business_impact
    ON disruptive_tech_articles (business_impact);

CREATE INDEX IF NOT EXISTS idx_disruptive_tech_published_at
    ON disruptive_tech_articles (published_at DESC);

CREATE INDEX IF NOT EXISTS idx_disruptive_tech_fetched_at
    ON disruptive_tech_articles (fetched_at DESC);

-- ----------------------------------------------------------------------------
-- Row Level Security — disabled to match the home_news_articles pattern (reads
-- and writes go through the same Supabase key used by the rest of the pipeline).
-- ----------------------------------------------------------------------------
ALTER TABLE disruptive_tech_articles DISABLE ROW LEVEL SECURITY;
