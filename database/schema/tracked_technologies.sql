-- ============================================================================
-- tracked_technologies
-- Self-serve technology tracking — "adding a technology is one entry", as an
-- admin-UI entry instead of a code edit.
--
-- Rows here are merged with the static registry (technologies.py TECHNOLOGIES)
-- by technologies.registry(): everything downstream (article→tech matching,
-- placements, stage snapshots, dossiers) consumes the merged registry, so a
-- row added via POST /api/mot/technologies starts matching articles on the
-- next read. Keys are slugs derived from the label; they are the stable
-- identity used by technology_stage_history's primary key, so new keys simply
-- accumulate history from scratch. A DB key colliding with a static registry
-- key is SKIPPED at merge time (the static registry always wins) — the API
-- also rejects such inserts up front.
--
-- DELETE via the API is a soft archive (archived = TRUE): the row drops out of
-- the merged registry, but any stage history it accumulated is kept.
-- ============================================================================

CREATE TABLE IF NOT EXISTS tracked_technologies (
    key       TEXT        PRIMARY KEY,               -- slug (from the label), stable identity
    label     TEXT        NOT NULL,                  -- display name, 2-60 chars
    domain    TEXT        NOT NULL,                  -- one of the registry's domain labels
    keywords  JSONB       NOT NULL DEFAULT '[]',     -- lowercased substrings that map an article here (1-10)
    added_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived  BOOLEAN     NOT NULL DEFAULT FALSE     -- soft delete; stage history is kept
);

CREATE INDEX IF NOT EXISTS tracked_technologies_active_idx
    ON tracked_technologies (added_at DESC) WHERE NOT archived;

ALTER TABLE tracked_technologies DISABLE ROW LEVEL SECURITY;
