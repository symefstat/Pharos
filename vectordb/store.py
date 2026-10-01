"""
Supabase pgvector store + retrieval for the MOT knowledge base.
Mirrors the proven GigGuru pattern (a chunk table + a cosine-search RPC).
"""

from __future__ import annotations

import logging
import re

from supabase import Client

from config import Config
from db import get_supabase

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\(\s*(19|20)\d{2}\s*\)")          # "(2017)" — reference years
_INDEX_RE = re.compile(r"[A-Za-z][A-Za-z.\-’']+,\s+\d{1,4}\b")  # "Tarakci, 40" — index entries

# Cosine-similarity floor for theory retrieval, mirroring _NEWS_SIM_FLOOR in
# analytics/ask.py (0.45, calibrated). Theory chunks are longer and denser than
# one-sentence news summaries, so on-topic passages score lower against a short
# query — the floor starts lower, at 0.35. This is a FIRST calibration, not a
# measured one like the news floor: revisit against real queries once per-hit
# similarities have been observed in the wild. Hits below the floor are dropped
# outright; an empty result is valid (the Ask prompt instructs abstention from
# [T#] citations when the theory pack is empty) and is strictly better than
# padding the pack with irrelevant chunks that invite decorative citations.
_THEORY_SIM_FLOOR = 0.35


def is_useful_chunk(text: str, min_chars: int = 180) -> bool:
    """Heuristic: is this chunk substantive prose, or retrieval noise?

    Drops the chunks that make the 'cited theory' look bad — book index pages,
    figure/number dumps, and reference/bibliography lists — keeping actual
    explanatory text. Pure; no network.
    """
    t = (text or "").strip()
    if len(t) < min_chars:
        return False
    digits = sum(c.isdigit() for c in t)
    if digits / len(t) > 0.10:                      # figure dumps / transistor counts / page nums
        return False
    if t.count("doi.org") >= 2 or len(_YEAR_RE.findall(t)) >= 5:  # bibliographies
        return False
    if len(_INDEX_RE.findall(t)) >= 8:              # book index pages ("Name, 123" repeated)
        return False
    letters = sum(c.isalpha() for c in t)
    if letters / len(t) < 0.55:                     # mostly punctuation/numbers/whitespace
        return False
    return True


class MotKnowledgeBase:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()
        self.table = Config.MOT_KB_TABLE

    def clear(self) -> int:
        """Delete all chunks (used by ingest_mot.py --reset for a clean re-load).

        Deletes in id-batches: a single delete over a large KB (tens of thousands
        of rows) exceeds Supabase's per-statement timeout and silently no-ops, so
        we page through ids and delete a chunk at a time until the table is empty.
        """
        removed = 0
        try:
            while True:
                ids = [r["id"] for r in (
                    self.client.table(self.table).select("id")
                    .order("id").limit(1000).execute().data or []
                )]
                if not ids:
                    break
                self.client.table(self.table).delete().in_("id", ids).execute()
                removed += len(ids)
        except Exception as e:
            logger.warning("KB clear failed after %d rows: %s", removed, e)
        return removed

    def ingested_files(self) -> set[str]:
        """Source files that already have chunks (used to skip re-ingestion).

        Paginated — PostgREST caps a plain select at 1000 rows, which for a large
        KB would report only a handful of files and break idempotency."""
        files: set[str] = set()
        start = 0
        try:
            while True:
                chunk = (self.client.table(self.table).select("source_file")
                         .range(start, start + 999).execute().data or [])
                files.update(r["source_file"] for r in chunk if r.get("source_file"))
                if len(chunk) < 1000:
                    break
                start += 1000
        except Exception as e:
            logger.warning("KB read failed: %s", e)
        return files

    def insert_chunks(self, rows: list[dict], batch: int = 40) -> int:
        """Upsert chunks in small batches to stay under the DB statement timeout.

        Each inserted vector triggers HNSW index maintenance, so a single large
        statement can exceed Supabase's per-statement timeout (~8s on the anon
        role). We batch, and if a batch still times out we fall back to one row
        at a time so the ingest always makes progress.
        """
        if not rows:
            return 0
        total = 0
        for i in range(0, len(rows), batch):
            part = rows[i : i + batch]
            try:
                resp = self.client.table(self.table).upsert(
                    part, on_conflict="source_file,chunk_index"
                ).execute()
                total += len(resp.data) if resp.data else 0
            except Exception as e:
                logger.warning("Batch upsert of %d rows failed (%s) — retrying row-by-row", len(part), e)
                for r in part:
                    try:
                        resp = self.client.table(self.table).upsert(
                            [r], on_conflict="source_file,chunk_index"
                        ).execute()
                        total += len(resp.data) if resp.data else 0
                    except Exception as e2:
                        logger.warning(
                            "Row upsert failed for %s#%s: %s",
                            r.get("source_file"), r.get("chunk_index"), e2,
                        )
        return total

    def search(self, query_embedding: list[float], k: int = 8) -> list[dict]:
        """Cosine search, then two relevance gates:

        1. similarity >= _THEORY_SIM_FLOOR — off-topic passages are dropped, and
           an EMPTY result is a valid answer (downstream prompts abstain from
           theory citations when the pack is empty);
        2. is_useful_chunk — index pages, figure dumps and reference lists are
           dropped even when they score above the floor.

        Over-fetches so the gates can still return k passages when good ones
        exist. The old "fall back to the raw hits if filtering empties the list"
        behaviour is gone deliberately: it re-padded the pack with junk/off-topic
        chunks, which invited decorative [T#] citations.
        """
        try:
            resp = self.client.rpc(
                "match_mot_chunks",
                {"query_embedding": query_embedding, "match_count": k + 12},
            ).execute()
            rows = resp.data or []
        except Exception as e:
            logger.warning("KB search failed: %s", e)
            return []
        relevant = [r for r in rows
                    if float(r.get("similarity") or 0.0) >= _THEORY_SIM_FLOOR]
        useful = [r for r in relevant if is_useful_chunk(r.get("chunk_text", ""))]
        if not useful and rows:
            logger.info("KB search: %d hits, none above floor %.2f and useful — "
                        "returning empty theory pack.", len(rows), _THEORY_SIM_FLOOR)
        return useful[:k]

    def stats(self) -> dict:
        try:
            files = len(self.ingested_files())
            cnt = self.client.table(self.table).select("id", count="exact").limit(1).execute()
            return {"files": files, "chunks": cnt.count or 0}
        except Exception as e:
            logger.warning("KB stats failed: %s", e)
            return {"files": 0, "chunks": 0}
