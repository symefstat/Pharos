-- ============================================================================
-- mot_knowledge_base
-- RAG vector store for the MOT (Management of Technology) corpus. One row per
-- text chunk + its embedding. Populated by ingest_mot.py (OpenAI
-- text-embedding-3-large, reduced to 2000 dims to fit pgvector's HNSW limit).
-- Queried via match_mot_chunks() (cosine similarity).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS mot_knowledge_base (
    id           BIGSERIAL PRIMARY KEY,
    source_file  TEXT        NOT NULL,        -- path relative to the MOT project folder
    chunk_index  INTEGER     NOT NULL,        -- 0-based position within the document
    chunk_text   TEXT        NOT NULL,
    embedding    VECTOR(2000),
    char_count   INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_file, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_mot_kb_source ON mot_knowledge_base (source_file);

-- Approximate-nearest-neighbour index for fast cosine search.
CREATE INDEX IF NOT EXISTS idx_mot_kb_embedding
    ON mot_knowledge_base USING hnsw (embedding vector_cosine_ops);

-- Cosine-similarity search. similarity = 1 - cosine_distance, so higher = closer.
CREATE OR REPLACE FUNCTION match_mot_chunks(
    query_embedding VECTOR(2000),
    match_count     INT DEFAULT 8
)
RETURNS TABLE (
    id           BIGINT,
    source_file  TEXT,
    chunk_index  INTEGER,
    chunk_text   TEXT,
    similarity   FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT id, source_file, chunk_index, chunk_text,
           1 - (embedding <=> query_embedding) AS similarity
    FROM mot_knowledge_base
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;

ALTER TABLE mot_knowledge_base DISABLE ROW LEVEL SECURITY;
