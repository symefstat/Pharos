-- ============================================================================
-- home_news_articles
-- Universal news feed for the Streamlit Home page (not per-user).
-- Populated by home_news_run.py via the Toqan Home Page News Agent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS home_news_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',
    companies       TEXT[]      DEFAULT '{}',  -- platforms/employers named in the article
    -- Would an informed investor plausibly re-price the stock on this?
    --   'material'   = earnings/guidance, M&A, exec change, binding regulation or
    --                  ruling, mass reclassification, major outage
    --   'contextual' = relevant backdrop, no direct re-pricing (single strike,
    --                  product launch, market-share report)
    --   'none'       = human-interest / isolated incident (e.g. one worker accident)
    business_impact TEXT,
    -- Why the article names the company/companies it does:
    --   'single-company' = one platform is the subject
    --   'sector'         = industry trend naming several players, none the subject
    --   'regulatory'     = law/lawsuit/government action hitting multiple companies
    --   'deal'           = M&A / stake change / funding / JV / partnership / joint
    --                      campaign between named companies
    --   'comparison'     = ranking / listicle / "best apps" roundup
    scope           TEXT,
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent ALTER for existing deployments that pre-date the companies column.
ALTER TABLE home_news_articles
    ADD COLUMN IF NOT EXISTS companies TEXT[] DEFAULT '{}';

-- Company/platform-oriented sentiment of the development: 'positive' (good for
-- the platform's business), 'negative' (bad for it), or 'neutral'. Populated by
-- the Home News agent; NULL for rows fetched before sentiment was added.
ALTER TABLE home_news_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

-- Business/stock materiality + multi-company scope. Both populated by the Home
-- News agent; NULL for rows fetched before these were added. Kept as separate
-- CHECKs so they can be added idempotently to existing deployments.
ALTER TABLE home_news_articles
    ADD COLUMN IF NOT EXISTS business_impact TEXT
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE home_news_articles
    ADD COLUMN IF NOT EXISTS scope TEXT;

-- scope allowed values are managed as a named constraint so the set can be
-- widened idempotently. 'deal' covers M&A / stake changes / funding / JVs /
-- partnerships / joint campaigns between named companies; 'comparison' is
-- rankings / roundups only.
ALTER TABLE home_news_articles DROP CONSTRAINT IF EXISTS home_news_articles_scope_check;
ALTER TABLE home_news_articles ADD CONSTRAINT home_news_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

-- Stock view filters to material news; index supports that predicate.
CREATE INDEX IF NOT EXISTS idx_home_news_business_impact
    ON home_news_articles (business_impact);

CREATE INDEX IF NOT EXISTS idx_home_news_published_at
    ON home_news_articles (published_at DESC);

CREATE INDEX IF NOT EXISTS idx_home_news_fetched_at
    ON home_news_articles (fetched_at DESC);

-- ----------------------------------------------------------------------------
-- Row Level Security
-- This table is universal (same for everyone) and both reads and writes happen
-- through the same Supabase key used by the rest of the pipeline (anon key, in
-- this project). RLS is left DISABLED to match the gig_news / KB pattern.
-- If a service-role key is added later, RLS can be enabled with a write policy
-- restricted to service_role and a public-read policy for anon/authenticated.
-- ----------------------------------------------------------------------------
ALTER TABLE home_news_articles DISABLE ROW LEVEL SECURITY;
