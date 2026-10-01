"""
Supabase pgvector store + retrieval for the recent-news corpus.

Mirrors vectordb/store.py (the MOT knowledge base): a chunk-per-article table
keyed by URL, plus a cosine-search RPC (match_news_chunks). Populated by
news_embed.py; queried by analytics.ask for the hybrid (vector + keyword) news
retrieval.
"""

from __future__ import annotations

import logging

from supabase import Client

from config import Config
from db import get_supabase

logger = logging.getLogger(__name__)


class NewsVectorStore:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()
        self.table = Config.NEWS_EMB_TABLE

    def clear(self) -> int:
        """Delete every embedded article (used by news_embed.py --reset)."""
        try:
            resp = self.client.table(self.table).delete().gte("id", 0).execute()
            return len(resp.data) if resp.data else 0
        except Exception as e:
            logger.warning("news_embeddings clear failed: %s", e)
            return 0

    def embedded_urls(self) -> set[str]:
        """URLs that already have an embedding (used to skip re-embedding)."""
        urls: set[str] = set()
        start = 0
        try:
            while True:
                chunk = (self.client.table(self.table).select("url")
                         .range(start, start + 999).execute().data or [])
                urls.update(r["url"] for r in chunk if r.get("url"))
                if len(chunk) < 1000:
                    break
                start += 1000
        except Exception as e:
            logger.warning("news_embeddings read failed: %s", e)
        return urls

    def upsert(self, rows: list[dict], batch: int = 100) -> int:
        """Upsert embedded articles in batches (on_conflict=url), falling back to
        one row at a time if a batch trips the statement timeout — same
        resilience pattern as MotKnowledgeBase.insert_chunks."""
        if not rows:
            return 0
        total = 0
        for i in range(0, len(rows), batch):
            part = rows[i : i + batch]
            try:
                resp = self.client.table(self.table).upsert(
                    part, on_conflict="url"
                ).execute()
                total += len(resp.data) if resp.data else 0
            except Exception as e:
                logger.warning("Batch upsert of %d rows failed (%s) — retrying row-by-row", len(part), e)
                for r in part:
                    try:
                        resp = self.client.table(self.table).upsert(
                            [r], on_conflict="url"
                        ).execute()
                        total += len(resp.data) if resp.data else 0
                    except Exception as e2:
                        logger.warning("Row upsert failed for %s: %s", r.get("url"), e2)
        return total

    def search(self, query_embedding: list[float], k: int = 12,
               since: str | None = None) -> list[dict]:
        """Cosine search over the news vectors. `since` (an ISO date string)
        restricts to recent stories; None searches the whole corpus."""
        try:
            resp = self.client.rpc(
                "match_news_chunks",
                {"query_embedding": query_embedding, "match_count": k, "since": since},
            ).execute()
            return resp.data or []
        except Exception as e:
            logger.warning("news vector search failed: %s", e)
            return []

    def stats(self) -> dict:
        try:
            cnt = self.client.table(self.table).select("id", count="exact").limit(1).execute()
            return {"articles": cnt.count or 0}
        except Exception as e:
            logger.warning("news_embeddings stats failed: %s", e)
            return {"articles": 0}
