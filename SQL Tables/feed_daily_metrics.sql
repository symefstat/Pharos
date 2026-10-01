-- ============================================================================
-- feed_daily_metrics
-- Never-pruned per-feed daily rollup that backs long-range trend analysis.
-- The feed tables prune at 14–30 days; this accumulates history. Maintained by
-- analytics/rollup.py (RollupBuilder), upserted on (feed, metric_date).
-- Rows are cross-feed de-duplicated before counting (a syndicated story counts
-- only under the first feed it appears in, FEEDS order), so the cross-feed reads
-- don't double-count it.
-- ============================================================================

CREATE TABLE IF NOT EXISTS feed_daily_metrics (
    feed            TEXT        NOT NULL,   -- feed key: ev, ai-energy, disruption, chips, …
    metric_date     DATE        NOT NULL,   -- the day summarised (published_at)
    total_articles  INTEGER     NOT NULL DEFAULT 0,  -- unique stories first-seen in this feed (post cross-feed dedup)
    by_tag          JSONB       NOT NULL DEFAULT '{}',   -- {tag: count}
    by_company      JSONB       NOT NULL DEFAULT '{}',   -- {canonical company: count}
    by_country      JSONB       NOT NULL DEFAULT '{}',   -- {ISO/GLOBAL: count}
    by_sentiment    JSONB       NOT NULL DEFAULT '{}',   -- {positive/negative/neutral: count}
    by_impact       JSONB       NOT NULL DEFAULT '{}',   -- {material/contextual/none: count}
    by_scope        JSONB       NOT NULL DEFAULT '{}',   -- {single-company/sector/regulatory/deal/comparison: count}
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (feed, metric_date)
);

CREATE INDEX IF NOT EXISTS idx_feed_daily_metrics_date
    ON feed_daily_metrics (metric_date DESC);
CREATE INDEX IF NOT EXISTS idx_feed_daily_metrics_feed
    ON feed_daily_metrics (feed, metric_date DESC);

ALTER TABLE feed_daily_metrics DISABLE ROW LEVEL SECURITY;
