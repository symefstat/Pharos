-- ============================================================================
-- MOT Lens columns — Management-of-Technology framework annotations on every
-- feed table. Idempotent; safe to re-run.
--   maturity_stage  — Technology Dynamics / S-curve lifecycle stage
--   adoption_stage  — High-Tech Marketing / diffusion of innovation (Rogers/Moore)
--   strategic_move  — Technology, Strategy & Entrepreneurship (Schilling)
--   lens_rationale  — one-sentence justification (free text)
-- Populated by analytics/lens.py via the Toqan MOT Lens agent. NULL = not yet
-- classified. See feeds.py for the table list.
-- ============================================================================

DO $$
DECLARE
    t text;
    feed_tables text[] := ARRAY[
        'home_news_articles', 'ai_energy_news_articles', 'disruptive_tech_articles',
        'semiconductor_news_articles', 'geopolitics_trade_articles',
        'climate_energy_articles', 'biotech_health_articles',
        'software_security_articles', 'fintech_articles', 'defense_space_articles',
        'prosus_portfolio_articles'
    ];
BEGIN
    FOREACH t IN ARRAY feed_tables LOOP
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS maturity_stage TEXT', t);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS adoption_stage TEXT', t);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS strategic_move TEXT', t);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS lens_rationale TEXT', t);
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS lens_classified_at TIMESTAMPTZ', t);

        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', t, t || '_maturity_chk');
        EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (maturity_stage IS NULL OR maturity_stage IN (''research'',''emerging'',''growth'',''dominant-design'',''mature'',''declining'',''n/a''))', t, t || '_maturity_chk');

        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', t, t || '_adoption_chk');
        EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (adoption_stage IS NULL OR adoption_stage IN (''innovators'',''early-adopters'',''early-majority'',''late-majority'',''laggards'',''n/a''))', t, t || '_adoption_chk');

        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', t, t || '_move_chk');
        EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (strategic_move IS NULL OR strategic_move IN (''standards-battle'',''entry-timing'',''collaboration'',''appropriability'',''platform'',''disruption'',''none''))', t, t || '_move_chk');

        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I (maturity_stage)', 'idx_' || t || '_maturity', t);
    END LOOP;
END $$;
