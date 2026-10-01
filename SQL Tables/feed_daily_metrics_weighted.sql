-- ============================================================================
-- feed_daily_metrics.by_company_breakdown — additive migration. Idempotent;
-- safe to re-run.
--
-- Per-company mention counts split by "<impact>|<tier>", so the ranked views
-- (Share of Voice, top companies, entity ranking) can weight by significance
-- (business_impact) and source authority (publisher tier) at READ time — keeping
-- the weights re-tunable without rebuilding the never-pruned rollup history.
--   e.g. { "Nvidia": { "material|t1": 2, "contextual|unknown": 1 } }
--
-- Maintained by analytics/rollup.py (RollupBuilder); folded through the weights
-- in analytics/weights.py by the read layer. Old rows default to '{}' and the
-- read layer falls back to the raw by_company column for them.
-- ============================================================================

ALTER TABLE feed_daily_metrics
    ADD COLUMN IF NOT EXISTS by_company_breakdown JSONB NOT NULL DEFAULT '{}';
