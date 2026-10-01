-- ============================================================================
-- prosus_tags — Prosus portfolio-company tags on every feed table
-- (pending-column migration).
--
--   prosus_tags — slugs from prosus_companies (SQL Tables/prosus_companies.sql)
--                 matched against the article's title/summary/companies by
--                 prosus/matcher.py. Written at upsert time by
--                 home_news/writer.py; historical rows are tagged by
--                 prosus_backfill.py. '{}' = no Prosus company named.
--
-- Region filtering needs NO new column: the feed tables' existing `country`
-- column (ISO-3166 alpha-2) is mapped to Prosus-lens regions at query time by
-- prosus/regions.py.
--
-- Until this is applied, the writer degrades — it strips the column and
-- retries the upsert (same pattern as `provenance`, see SQL Tables/
-- feed_provenance_column.sql) — so feed runs never break on the pending
-- migration; articles simply stay untagged until backfill.
--
-- GIN indexes support the Prosus page's `prosus_tags && ARRAY[...]` filters.
--
-- Idempotent; safe to re-run. Apply AFTER SQL Tables/prosus_companies.sql.
-- ============================================================================

ALTER TABLE home_news_articles          ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE ai_energy_news_articles     ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE disruptive_tech_articles    ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE semiconductor_news_articles ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE geopolitics_trade_articles  ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE climate_energy_articles     ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE biotech_health_articles     ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE software_security_articles  ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE fintech_articles            ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE defense_space_articles      ADD COLUMN IF NOT EXISTS prosus_tags TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_home_news_prosus_tags      ON home_news_articles          USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_ai_energy_prosus_tags      ON ai_energy_news_articles     USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_disruptive_prosus_tags     ON disruptive_tech_articles    USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_semiconductor_prosus_tags  ON semiconductor_news_articles USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_geopolitics_prosus_tags    ON geopolitics_trade_articles  USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_climate_prosus_tags        ON climate_energy_articles     USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_biotech_prosus_tags        ON biotech_health_articles     USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_software_prosus_tags       ON software_security_articles  USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_fintech_prosus_tags        ON fintech_articles            USING GIN (prosus_tags);
CREATE INDEX IF NOT EXISTS idx_defense_prosus_tags        ON defense_space_articles      USING GIN (prosus_tags);
