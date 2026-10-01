#!/usr/bin/env python3
"""
Ingest the MOT corpus into the Supabase pgvector knowledge base.

    extract text → chunk → embed (OpenAI) → upsert into mot_knowledge_base

Idempotent: files already present in the KB are skipped, so re-running only
picks up new/changed documents. Run once after applying
`database/schema/mot_knowledge_base.sql` and setting OPENAI_API_KEY.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config
from vectordb.chunker import chunk_text
from vectordb.embedder import embed_texts
from vectordb.extract import SUPPORTED, extract_text
from vectordb.store import MotKnowledgeBase

logger = logging.getLogger("ingest_mot")

# Ingest ONLY the authoritative theory set — the sorted "provided" bucket
# (papers, textbooks, lecture slides, cases). The KB is what the Ask/Strategist
# agents cite as [T#], so student work (assignments, reflections, summaries)
# stays out. See `MOT project/_My work & projects/` for the excluded half.
MOT_DIR = Path(__file__).resolve().parents[1] / "MOT project" / "_Papers, books & materials"

# Non-theory files that live in the provided bucket but must not enter the KB:
# past exams, datasets, course descriptions, and assignment briefs/rubrics.
_EXCLUDE_RE = re.compile(
    r"tentamen|vragen|questions-and-answers|model.?answers|sample-questions|"
    r"prac?tice.?exam|re-exam|resit-exam|-exam-|exam-\d|student copy exam|"
    r"mot2421_exam|mot2313|course discription|/data sets/|dataset\(|"
    r"data_hoverpen|data_jotter|block 0 dataset|\bguidelines?\b|\brubric|"
    r"\btemplate\b|assignment description|\.csv$|\.zip$",
    re.IGNORECASE,
)


def _is_theory(rel: str) -> bool:
    return not _EXCLUDE_RE.search(rel)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_dotenv()

    if not Config.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not set in .env — cannot embed.")
        return 1
    if not MOT_DIR.exists():
        logger.error(
            "Theory corpus folder not found at %s — run the file sort first "
            "(the '_Papers, books & materials' bucket).", MOT_DIR,
        )
        return 1

    kb = MotKnowledgeBase()
    if "--reset" in sys.argv[1:]:
        cleared = kb.clear()
        logger.info("Reset: cleared %d existing chunks before re-ingesting.", cleared)
    already = kb.ingested_files()
    files = sorted(
        p for p in MOT_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED and p.name != ".DS_Store"
        and _is_theory(str(p.relative_to(MOT_DIR)))
    )
    logger.info("Found %d theory files to ingest; %d already in the KB.", len(files), len(already))

    new_chunks = 0
    for p in files:
        rel = str(p.relative_to(MOT_DIR))
        if rel in already:
            continue
        text = extract_text(p)
        chunks = chunk_text(text, size=Config.MOT_CHUNK_CHARS, overlap=Config.MOT_CHUNK_OVERLAP)
        if not chunks:
            logger.info("skip (no extractable text): %s", rel)
            continue
        try:
            embeddings = embed_texts(chunks)
        except Exception as e:
            logger.warning("embedding failed for %s: %s", rel, e)
            continue
        rows = [
            {
                "source_file": rel,
                "chunk_index": i,
                "chunk_text": c,
                "char_count": len(c),
                "embedding": emb,
            }
            for i, (c, emb) in enumerate(zip(chunks, embeddings))
        ]
        new_chunks += kb.insert_chunks(rows)
        logger.info("ingested %s (%d chunks)", rel, len(rows))

    logger.info("Done. %d new chunks. KB now holds %s", new_chunks, kb.stats())
    return 0


if __name__ == "__main__":
    sys.exit(main())
