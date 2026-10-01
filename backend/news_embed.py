#!/usr/bin/env python3
"""
Embed the recent-news corpus into the Supabase pgvector store (news_embeddings).

    read articles (all feed tables) → dedup by URL → embed (OpenAI) → upsert

Idempotent: URLs already embedded are skipped, so re-running only picks up new
articles. Run once after applying `database/schema/news_embeddings.sql` and setting
OPENAI_API_KEY; thereafter the refresh pipeline (backend/app/actions.py) calls
`run()` to keep it fresh.

    ./venv/bin/python backend/news_embed.py            # incremental (embed new URLs)
    ./venv/bin/python backend/news_embed.py --reset    # clear + re-embed everything
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config

logger = logging.getLogger("news_embed")

_FIELDS = ("url", "title", "summary", "companies", "tags", "business_impact", "published_at")


def _embed_text(row: dict) -> str:
    """What we embed per article: title + summary, with the named companies and
    tags appended so entity/topic queries match even when the prose doesn't."""
    parts = [str(row.get("title") or ""), str(row.get("summary") or "")]
    companies = row.get("companies") or []
    tags = row.get("tags") or []
    if companies:
        parts.append("companies: " + ", ".join(str(c) for c in companies))
    if tags:
        parts.append("tags: " + ", ".join(str(t) for t in tags))
    return "\n".join(p for p in parts if p).strip()


def _collect_articles(client) -> list[dict]:
    """All articles across every feed table, deduped by normalized URL (first
    feed wins), annotated with feed_key/feed_label. Mirrors the aggregator's
    URL-dedup so a syndicated story is embedded once."""
    from feeds import FEEDS
    from analytics.aggregator import _normalize_url

    out: list[dict] = []
    seen: set[str] = set()
    for feed in FEEDS:
        start = 0
        while True:
            try:
                chunk = (client.table(feed.table).select(",".join(_FIELDS))
                         .range(start, start + 999).execute().data or [])
            except Exception as e:
                logger.warning("read %s failed: %s", feed.table, e)
                break
            for row in chunk:
                url = row.get("url")
                norm = _normalize_url(url or "")
                if not url or (norm and norm in seen):
                    continue
                if norm:
                    seen.add(norm)
                out.append({
                    "url": url,
                    "feed_key": feed.key,
                    "feed_label": feed.label,
                    "title": row.get("title"),
                    "summary": row.get("summary"),
                    "companies": row.get("companies") or [],
                    "tags": row.get("tags") or [],
                    "business_impact": row.get("business_impact"),
                    "published_at": row.get("published_at"),
                })
            if len(chunk) < 1000:
                break
            start += 1000
    return out


def run(client=None, reset: bool = False) -> dict:
    """Embed new articles into news_embeddings. Returns a small summary dict.
    Safe to call from the refresh pipeline — degrades to a no-op summary on
    misconfiguration rather than raising."""
    if not Config.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — skipping news embedding.")
        return {"embedded": 0, "skipped": 0, "reason": "no OPENAI_API_KEY"}

    from db import get_supabase
    from vectordb.embedder import embed_texts
    from vectordb.news_store import NewsVectorStore

    client = client or get_supabase()
    store = NewsVectorStore(client)
    if reset:
        removed = store.clear()
        logger.info("Reset: cleared %d existing rows.", removed)

    articles = _collect_articles(client)
    already = set() if reset else store.embedded_urls()
    todo = [a for a in articles if a["url"] not in already]
    logger.info("%d articles total · %d already embedded · %d to embed",
                len(articles), len(already), len(todo))
    if not todo:
        return {"embedded": 0, "skipped": len(already), "total": len(articles)}

    vectors = embed_texts([_embed_text(a) for a in todo])
    for a, vec in zip(todo, vectors):
        a["embedding"] = vec
    embedded = store.upsert(todo)
    logger.info("Embedded %d new articles.", embedded)
    return {"embedded": embedded, "skipped": len(already), "total": len(articles)}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_dotenv()
    if not Config.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not set in .env — embeddings unavailable.")
        return 1
    summary = run(reset="--reset" in sys.argv)
    logger.info("Done: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
