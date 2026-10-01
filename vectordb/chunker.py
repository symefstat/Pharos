"""
Paragraph-aware character chunking with overlap.

Char-based (not token-based) on purpose: a ~2400-char chunk is well under the
embedding model's input limit, and avoiding a tokenizer dependency keeps the
pipeline light. Overlap carries a tail of the previous chunk so context isn't
lost at boundaries.
"""

from __future__ import annotations

import re

_WS_RE = re.compile(r"[ \t]+")


def clean(text: str) -> str:
    text = (text or "").replace("\r", "")
    # Postgres text/json can't store NUL (\x00); strip it and other control
    # characters (keeping \n and \t). Common in .ppt / binary extractions.
    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def chunk_text(text: str, size: int = 2400, overlap: int = 240) -> list[str]:
    """Split text into ~`size`-char chunks on paragraph boundaries, with overlap."""
    text = clean(text)
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for p in paragraphs:
        if current and len(current) + len(p) + 2 > size:
            chunks.append(current)
            current = ""
        if len(p) <= size:
            current = f"{current}\n\n{p}" if current else p
        else:
            # Paragraph longer than a chunk: sliding window over it.
            if current:
                chunks.append(current)
                current = ""
            start = 0
            step = max(1, size - overlap)
            while start < len(p):
                chunks.append(p[start : start + size])
                start += step
    if current:
        chunks.append(current)

    if overlap <= 0 or len(chunks) <= 1:
        return chunks

    # Prepend a tail of the previous chunk to each subsequent chunk for continuity.
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        tail = chunks[i - 1][-overlap:]
        out.append(f"{tail}\n{chunks[i]}")
    return out
