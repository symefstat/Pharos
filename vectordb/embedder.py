"""
OpenAI embeddings for the MOT knowledge base.

Uses text-embedding-3-large reduced to Config.EMBEDDING_DIMENSIONS (2000) via the
API's `dimensions` parameter, so the vectors fit pgvector's HNSW index limit.
The `openai` import is lazy so the rest of the app runs without the package.
"""

from __future__ import annotations

import logging

from config import Config

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set in .env — embeddings unavailable.")
        from openai import OpenAI  # lazy import — only needed for embeddings

        # timeout + max_retries so a slow/transient embedding call backs off and
        # retries (with jitter) instead of a single unguarded attempt that fails the run.
        _client = OpenAI(api_key=Config.OPENAI_API_KEY, timeout=30.0, max_retries=3)
    return _client


def embed_texts(texts: list[str], batch: int = 100) -> list[list[float]]:
    """Embed a list of texts; returns one vector per text, in order."""
    client = _get_client()
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        resp = client.embeddings.create(
            model=Config.EMBEDDING_MODEL,
            input=texts[i : i + batch],
            dimensions=Config.EMBEDDING_DIMENSIONS,
        )
        out.extend(d.embedding for d in resp.data)
    return out


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
