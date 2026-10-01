-- ============================================================================
-- Extraction provenance — the per-field audit trail on every feed table.
--   provenance — JSONB map {field: how_obtained}, where how_obtained is one of
--                'agent'    (canonical key, agent-supplied),
--                'keydrift' (alternate key the agent used, e.g. 'headline'→title),
--                'default'  (agent omitted/invalid → we filled a safe default),
--                'missing'  (omitted, stored null).
-- Captured at parse time by home_news/parser.py (`_field_provenance`) and surfaced
-- as the "show your work / cite this" trail per signal. NULL on rows that predate
-- this column — the reader (analytics/provenance.py) degrades to field coverage.
-- Idempotent; safe to re-run. Apply AFTER the feed tables exist. See feeds.py.
-- ============================================================================

DO $$
DECLARE
    t text;
    feed_tables text[] := ARRAY[
        'home_news_articles', 'ai_energy_news_articles', 'disruptive_tech_articles',
        'semiconductor_news_articles', 'geopolitics_trade_articles',
        'climate_energy_articles', 'biotech_health_articles',
        'software_security_articles', 'fintech_articles', 'defense_space_articles'
    ];
BEGIN
    FOREACH t IN ARRAY feed_tables LOOP
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS provenance JSONB', t);
    END LOOP;
END $$;
