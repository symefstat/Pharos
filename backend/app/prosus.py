"""
/api/prosus — the Prosus page: the group-portfolio lens over all of Lodestar.

One payload drives the whole page:
  - companies  — the prosus_companies reference table (segment tabs + filters)
  - stories    — every recent story that names a portfolio company (prosus_tags,
                 written by home_news/writer.py) plus everything from the
                 dedicated Prosus portfolio feed, annotated with a region
                 derived from `country` (prosus/regions.py)
  - forecasts  — Ledger entries whose claim names a portfolio company (matched
                 with the same alias index, so no schema change on predictions)

Filters (`region`, `segment`, `company`) narrow `stories`; the segment/region
counts are computed on the unfiltered set so the UI chips always show totals.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from . import data
from .auth import require_admin

router = APIRouter(tags=["prosus"])

SEGMENTS = [
    ("food-delivery", "Food Delivery"),
    ("payments-fintech", "Payments & Fintech"),
    ("classifieds", "Classifieds"),
    ("edtech", "Edtech"),
    ("ecommerce-travel", "Ecommerce & Travel"),
    ("mobility", "Mobility"),
    ("frontier-tech", "Frontier Tech"),
]
SEGMENT_LABELS = dict(SEGMENTS)
SEGMENT_LABELS["internet"] = "Internet"  # Tencent — shown as NAV anchor, not a tab

# The three strategic-geography lenses first; the rest exist so nothing is lost.
REGIONS = [
    ("latam", "Latin America"),
    ("india", "India"),
    ("europe", "Europe"),
    ("us", "North America"),
    ("china", "China"),
    ("sea", "Southeast Asia"),
    ("mena", "MENA"),
    ("africa", "Africa"),
    ("global", "Global"),
    ("other", "Other"),
]
REGION_LABELS = dict(REGIONS)

_STORY_FIELDS = (
    "title", "summary", "url", "source_name", "published_at", "country",
    "tags", "companies", "prosus_tags", "sentiment", "business_impact",
    "scope", "image_url", "_feed_key", "_feed_label", "_feed_icon",
)


def _companies() -> list[dict]:
    """prosus_companies reference rows, cached. [] when the table isn't set up
    (the endpoint still serves the dedicated feed's stories)."""

    def load() -> list[dict]:
        try:
            return (
                data._supabase().table("prosus_companies")
                .select("*").order("tier").order("name")
                .execute().data or []
            )
        except Exception:
            return []

    return data._cache.get_or_set("prosus_companies", ttl=900, producer=load)


def _slim(r: dict, region: str) -> dict:
    out = {k: r.get(k) for k in _STORY_FIELDS}
    out["region"] = region
    return out


def _prosus_stories(days: int) -> list[dict]:
    """Portfolio-relevant stories across every feed: anything tagged with a
    portfolio company, plus the dedicated Prosus feed in full (competitor and
    core-market stories carry no tag but belong on the page)."""
    from prosus.regions import region_for_country

    out = []
    for r in data.rows(days=days):
        if not (r.get("prosus_tags") or r.get("_feed_key") == "prosus"):
            continue
        out.append(_slim(r, region_for_country(r.get("country"))))
    out.sort(key=lambda s: s.get("published_at") or "", reverse=True)
    return out


def _prosus_forecasts(companies: list[dict]) -> list[dict]:
    """Ledger entries that name a portfolio company — alias-matched on the
    claim text, so the predictions table needs no Prosus column."""
    from prosus.matcher import build_alias_index, match_prosus_tags

    index = build_alias_index(companies)
    if not index:
        return []
    out = []
    for p in data.predictions():
        blob = " ".join(filter(None, [p.get("claim"), p.get("subject"), p.get("basis")]))
        tags = match_prosus_tags(index, blob, None)
        if tags:
            out.append({**p, "prosus_tags": tags})
    return out


@router.get("/api/prosus", dependencies=[Depends(require_admin)])
def prosus(region: str | None = None, segment: str | None = None,
           company: str | None = None,
           days: int = Query(default=30, ge=1, le=365)) -> dict:
    companies = _companies()
    segments_by_slug = {c["slug"]: c["segment"] for c in companies}

    stories = _prosus_stories(days)

    def story_segments(s: dict) -> set[str]:
        return {segments_by_slug[t] for t in (s.get("prosus_tags") or [])
                if t in segments_by_slug}

    # Chip counts on the unfiltered set, so totals don't shift as you filter.
    region_counts: dict[str, int] = {}
    segment_counts: dict[str, int] = {}
    for s in stories:
        region_counts[s["region"]] = region_counts.get(s["region"], 0) + 1
        for seg in story_segments(s):
            segment_counts[seg] = segment_counts.get(seg, 0) + 1

    if region:
        stories = [s for s in stories if s["region"] == region]
    if segment:
        stories = [s for s in stories if segment in story_segments(s)]
    if company:
        stories = [s for s in stories if company in (s.get("prosus_tags") or [])]

    return {
        "configured": bool(companies),
        "companies": companies,
        "segments": [
            {"key": k, "label": lbl, "count": segment_counts.get(k, 0)}
            for k, lbl in SEGMENTS
        ],
        "regions": [
            {"key": k, "label": lbl, "count": region_counts.get(k, 0)}
            for k, lbl in REGIONS
        ],
        # Generous cap: the SPA fetches once unfiltered and applies the
        # region/segment/company lenses client-side.
        "stories": stories[:200],
        "total_stories": len(stories),
        "forecasts": _prosus_forecasts(companies)[:20],
    }
