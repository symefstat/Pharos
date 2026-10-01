-- ============================================================================
-- ai_energy_news_articles
-- News feed for the "AI & Energy" tab — AI's energy / environmental footprint
-- (data-center demand, carbon/water/land, grid, power deals, policy).
-- Populated by home_news_run.py via the Toqan AI Energy Impact Agent.
-- Same shape as home_news_articles; kept as a separate table per feed so the
-- two topics stay cleanly organised. See feeds.py for the feed→table mapping.
-- ============================================================================

CREATE TABLE IF NOT EXISTS ai_energy_news_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- energy-demand, data-center, grid, carbon, water, policy, …
    companies       TEXT[]      DEFAULT '{}',   -- AI labs / hyperscalers / chipmakers / utilities named
    -- Would an informed investor plausibly re-price a named company's stock?
    --   'material'   = power-procurement / nuclear / PPA deal, binding regulation
    --                  or grid-connection moratorium, earnings-relevant capex
    --   'contextual' = relevant backdrop, no direct re-pricing (single project,
    --                  regional grid story, market/survey report)
    --   'none'       = systemic / human-interest (agency dataset, footprint study,
    --                  household-prices story)
    business_impact TEXT,
    -- Why the article names the company/companies it does:
    --   'single-company' = one company is the subject
    --   'sector'         = industry-wide trend naming several players
    --   'regulatory'     = law / roadmap / mandate / siting policy
    --   'deal'           = PPA / nuclear offtake / investment / JV between named parties
    --   'comparison'     = ranking / head-to-head of footprints or efficiency
    scope           TEXT,
    sentiment       TEXT,           -- AI/tech-industry view: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- CHECK constraints on the controlled-vocabulary fields (added as named
-- constraints so the allowed sets can be widened idempotently later).
ALTER TABLE ai_energy_news_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE ai_energy_news_articles DROP CONSTRAINT IF EXISTS ai_energy_news_articles_sentiment_check;
ALTER TABLE ai_energy_news_articles ADD CONSTRAINT ai_energy_news_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE ai_energy_news_articles DROP CONSTRAINT IF EXISTS ai_energy_news_articles_business_impact_check;
ALTER TABLE ai_energy_news_articles ADD CONSTRAINT ai_energy_news_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE ai_energy_news_articles DROP CONSTRAINT IF EXISTS ai_energy_news_articles_scope_check;
ALTER TABLE ai_energy_news_articles ADD CONSTRAINT ai_energy_news_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_ai_energy_news_business_impact
    ON ai_energy_news_articles (business_impact);

CREATE INDEX IF NOT EXISTS idx_ai_energy_news_published_at
    ON ai_energy_news_articles (published_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_energy_news_fetched_at
    ON ai_energy_news_articles (fetched_at DESC);

-- ----------------------------------------------------------------------------
-- Row Level Security — disabled to match the home_news_articles pattern (reads
-- and writes go through the same Supabase key used by the rest of the pipeline).
-- ----------------------------------------------------------------------------
ALTER TABLE ai_energy_news_articles DISABLE ROW LEVEL SECURITY;
