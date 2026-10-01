"""
Events, not articles — cluster near-duplicate stories (the same development
covered by several outlets) into one event with a source count.

A cleaner feed, and a corroboration signal: an event carried by 5 independent
outlets is better-corroborated than a lone story (MOT's epistemic-rigor lens, G).
Pure, no network — greedy clustering by title-token overlap. Reads both the raw
row shape (`_feed_label`) and the slim story shape (`feed_label`).
"""

from __future__ import annotations

import re

# Small stopword set so the title signature keeps the meaningful tokens.
_STOP = {
    "the", "a", "an", "to", "for", "of", "in", "on", "and", "or", "with", "by",
    "as", "at", "is", "are", "be", "from", "its", "it", "into", "amid", "over",
    "after", "new", "says", "say", "will", "has", "have", "than", "that", "this",
    "up", "down", "out", "but", "not", "you", "your", "we", "our", "&",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _signature(title: str) -> frozenset:
    """Significant lowercased tokens of a headline (≥3 chars, minus stopwords)."""
    toks = _TOKEN_RE.findall((title or "").lower())
    return frozenset(t for t in toks if len(t) >= 3 and t not in _STOP)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


def cluster_events(rows: list[dict], threshold: float = 0.5, min_shared: int = 2) -> list[dict]:
    """Group rows into events. Two stories merge when their title signatures
    overlap enough (Jaccard ≥ threshold AND ≥ min_shared shared tokens).

    Returns events sorted by source count (most-corroborated first), each:
      {rep, count, sources:[...], feeds:[...], members:[...]}
    where `rep` is the most material / fullest story in the cluster.
    """
    clusters: list[dict] = []
    for r in rows:
        sig = _signature(r.get("title", ""))
        feed = r.get("_feed_label") or r.get("feed_label") or "?"
        src = (r.get("source_name") or "").strip()
        placed = False
        for cl in clusters:
            if len(sig & cl["sig"]) >= min_shared and _jaccard(sig, cl["sig"]) >= threshold:
                cl["members"].append(r)
                cl["sig"] = cl["sig"] | sig  # let the signature accrete
                if src:
                    cl["sources"].add(src)
                cl["feeds"].add(feed)
                placed = True
                break
        if not placed:
            clusters.append({
                "sig": sig, "members": [r],
                "sources": {src} if src else set(),
                "feeds": {feed},
            })

    events = []
    for cl in clusters:
        rep = max(cl["members"], key=lambda m: (
            1 if (m.get("business_impact") or "").lower() == "material" else 0,
            len(str(m.get("summary") or "")),
        ))
        events.append({
            "rep": rep,
            "count": len(cl["members"]),
            "sources": sorted(cl["sources"]),
            "feeds": sorted(cl["feeds"]),
            "members": cl["members"],
        })
    events.sort(key=lambda e: (-e["count"], -len(e["sources"])))
    return events


def multi_source_count(events: list[dict]) -> int:
    """How many events carry coverage from >1 distinct outlet — true corroboration.

    Counts distinct `sources`, NOT member stories: two rewrites from a single outlet
    cluster into one event with `count == 2` but `len(sources) == 1`, which is a
    single-source duplicate, not multi-source."""
    return sum(1 for e in events if len(e.get("sources") or []) > 1)
