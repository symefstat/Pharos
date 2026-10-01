-- ============================================================================
-- software_security_articles
-- News feed for the "Software & Cyber" tab — the top of the AI stack: enterprise
-- software, AI applications, developer tooling, cloud, and cybersecurity.
-- Populated by home_news_run.py via the Toqan Software & Cyber Agent.
-- Same shape as the other feed tables; one table per Lodestar feed. See feeds.py.
-- ============================================================================

CREATE TABLE IF NOT EXISTS software_security_articles (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT        NOT NULL,
    summary         TEXT        NOT NULL,
    url             TEXT        NOT NULL UNIQUE,
    source_name     TEXT,
    published_at    DATE,
    country         TEXT,           -- ISO-3166 alpha-2 or 'GLOBAL'
    tags            TEXT[]      DEFAULT '{}',   -- ai-app, saas, dev-tools, cloud, cybersecurity, breach, …
    companies       TEXT[]      DEFAULT '{}',   -- software / security firms named (Microsoft, Palantir, CrowdStrike, …)
    business_impact TEXT,           -- material / contextual / none (stock materiality)
    scope           TEXT,           -- single-company / sector / regulatory / deal / comparison
    sentiment       TEXT,           -- business view of the company named: positive / negative / neutral
    image_url       TEXT,           -- og:image / twitter:image scraped server-side
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE software_security_articles
    ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE software_security_articles DROP CONSTRAINT IF EXISTS software_security_articles_sentiment_check;
ALTER TABLE software_security_articles ADD CONSTRAINT software_security_articles_sentiment_check
    CHECK (sentiment IN ('positive', 'negative', 'neutral'));

ALTER TABLE software_security_articles DROP CONSTRAINT IF EXISTS software_security_articles_business_impact_check;
ALTER TABLE software_security_articles ADD CONSTRAINT software_security_articles_business_impact_check
    CHECK (business_impact IN ('material', 'contextual', 'none'));

ALTER TABLE software_security_articles DROP CONSTRAINT IF EXISTS software_security_articles_scope_check;
ALTER TABLE software_security_articles ADD CONSTRAINT software_security_articles_scope_check
    CHECK (scope IN ('single-company', 'sector', 'regulatory', 'comparison', 'deal'));

CREATE INDEX IF NOT EXISTS idx_software_security_business_impact
    ON software_security_articles (business_impact);
CREATE INDEX IF NOT EXISTS idx_software_security_published_at
    ON software_security_articles (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_software_security_fetched_at
    ON software_security_articles (fetched_at DESC);

ALTER TABLE software_security_articles DISABLE ROW LEVEL SECURITY;
