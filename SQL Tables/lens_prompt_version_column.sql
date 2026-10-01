-- ============================================================================
-- MOT Lens prompt-version column — provenance on every classified row.
--   lens_prompt_version — the id of the MOT Lens prompt that produced this row's
--       classification (e.g. 'mot-lens-v1'). NULL on rows classified before this
--       column existed.
-- Lets labels be attributed to a prompt and A/B-tested: score accuracy per
-- version (eval_run.py) to prove a rubric change improved the lens, then keep the
-- winner. Written by analytics/lens.py (echoed by the agent if present, else the
-- deployed LENS_PROMPT_VERSION constant). Idempotent; safe to re-run. Apply AFTER
-- the feed tables exist (see feeds.py). The writer degrades until it's applied.
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
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS lens_prompt_version TEXT', t);
    END LOOP;
END $$;
