-- ============================================================================
-- feed_runs
-- Never-pruned per-stage run-ledger: one row per (stage, feed) per pipeline run.
-- Turns the pipeline's stdout-only data losses into queryable metrics — the
-- measurement foundation the eval harness and the freshness monitor build on.
--
-- Written by analytics/run_ledger.py (RunLedger) from the batch jobs:
--   stage='parse'  feed=<key>  metrics={received,parsed,dropped_malformed,
--                                        dropped_dup,dropped_stale}     (home_news_run.py)
--   stage='lens'   feed=<key>  metrics={requested,returned,missing,batches} (lens_run.py)
-- The schema is stage-agnostic (metrics is JSONB) so later stages — rollup,
-- strategist, financials, forecasts — log here too without a migration.
-- Apply anytime; independent of the feed tables. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS feed_runs (
    id          BIGSERIAL   PRIMARY KEY,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- when the stage finished
    stage       TEXT        NOT NULL,                -- 'parse' | 'lens' | 'rollup' | …
    feed        TEXT,                                -- feed key; NULL for cross-feed stages
    ok          BOOLEAN     NOT NULL DEFAULT TRUE,   -- did the stage complete without error
    metrics     JSONB       NOT NULL DEFAULT '{}',   -- stage-specific counts (see header)
    error       TEXT                                 -- error summary when ok = FALSE
);

-- Freshness queries ("newest run per stage/feed") and history scans both walk by
-- time; the composite index serves the common "latest for this stage+feed" lookup.
CREATE INDEX IF NOT EXISTS idx_feed_runs_run_at
    ON feed_runs (run_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_runs_stage_feed
    ON feed_runs (stage, feed, run_at DESC);

ALTER TABLE feed_runs DISABLE ROW LEVEL SECURITY;
