-- ============================================================================
-- news_embeddings
-- Vector store for the recent-news corpus. One row per article (keyed by URL) +
-- its embedding, so the Ask agent can retrieve semantically-relevant stories
-- alongside the MOT theory (see mot_knowledge_base.sql). Populated by
-- news_embed.py (OpenAI text-embedding-3-large, reduced to 2000 dims to fit
-- pgvector's HNSW limit). Queried via match_news_chunks() (cosine similarity,
-- with an optional recency floor).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS news_embeddings (
    id              BIGSERIAL PRIMARY KEY,
    url             TEXT        NOT NULL UNIQUE,   -- stable per-article key (matches the feed tables)
    feed_key        TEXT,                          -- e.g. 'ai_energy' — the feed the story came from
    feed_label      TEXT,                          -- human label, surfaced in citations
    title           TEXT,
    summary         TEXT,
    companies       TEXT[]      DEFAULT '{}',
    tags            TEXT[]      DEFAULT '{}',
    business_impact TEXT,
    published_at    DATE,
    embedding       VECTOR(2000),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_emb_published_at
    ON news_embeddings (published_at DESC);

-- Approximate-nearest-neighbour index for fast cosine search.
CREATE INDEX IF NOT EXISTS idx_news_emb_embedding
    ON news_embeddings USING hnsw (embedding vector_cosine_ops);

-- Cosine-similarity search with an optional recency floor. similarity =
-- 1 - cosine_distance, so higher = closer. Pass `since` (a date) to restrict to
-- recent stories; NULL searches the whole corpus.
CREATE OR REPLACE FUNCTION match_news_chunks(
    query_embedding VECTOR(2000),
    match_count     INT  DEFAULT 12,
    since           DATE DEFAULT NULL
)
RETURNS TABLE (
    id              BIGINT,
    url             TEXT,
    feed_key        TEXT,
    feed_label      TEXT,
    title           TEXT,
    summary         TEXT,
    companies       TEXT[],
    tags            TEXT[],
    business_impact TEXT,
    published_at    DATE,
    similarity      FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT id, url, feed_key, feed_label, title, summary, companies, tags,
           business_impact, published_at,
           1 - (embedding <=> query_embedding) AS similarity
    FROM news_embeddings
    WHERE embedding IS NOT NULL
      AND (since IS NULL OR published_at >= since)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;

ALTER TABLE news_embeddings DISABLE ROW LEVEL SECURITY;
