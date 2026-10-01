"""
Significance & source weights for the ranked views (Share of Voice, top companies,
entity ranking).

The rollup stores a per-company breakdown keyed by "<impact>|<tier>"; the read
layer folds it through these weights so material news from reputable outlets
outranks high-volume noise — WITHOUT baking weights into stored data. The rollup
is never-pruned accumulating history, so build-time weights would freeze
permanently for any day older than the feed prune window; applying them here keeps
them re-tunable with zero rebuild. Tune the constants below and the change takes
effect on the next read.

Pure module — no I/O, importable from anywhere.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Iterator

# ── Significance (business_impact) ───────────────────────────────────────────
# Would an informed investor plausibly re-price on this? material > contextual > none.
# 'none' keeps a small positive weight so an entity seen ONLY in 'none' stories still
# appears (ranked low) rather than vanishing from the weighted universe entirely.
IMPACT_WEIGHTS: dict[str, float] = {"material": 3.0, "contextual": 1.0, "none": 0.25}
_DEFAULT_IMPACT = "contextual"  # mirrors the parser default for missing/invalid impact

# ── Source authority (tier) ──────────────────────────────────────────────────
# Reputable outlets count more; unknown free-text sources slightly less. The
# spread is deliberately modest so source nudges rather than dominates significance.
DEFAULT_TIER = "unknown"
TIER_WEIGHTS: dict[str, float] = {"t1": 1.5, "t2": 1.0, "unknown": 0.7}

# Publisher → tier. Keys are the normalized publisher name (see _normalize_source:
# lowercased, leading "the " dropped, URL/domain decoration stripped). Curated and
# deliberately small — add entries as you see source_name drift; anything not listed
# falls to DEFAULT_TIER. Mirrors the alias-map philosophy in analytics/entities.py.
SOURCE_TIERS: dict[str, str] = {
    # Tier 1 — wire services + financial papers of record.
    "reuters": "t1", "bloomberg": "t1", "associated press": "t1", "ap": "t1",
    "financial times": "t1", "ft": "t1", "wall street journal": "t1", "wsj": "t1",
    "new york times": "t1", "nyt": "t1", "economist": "t1", "nikkei": "t1",
    # Tier 2 — strong trade / tech / sector press.
    "cnbc": "t2", "verge": "t2", "techcrunch": "t2", "ars technica": "t2",
    "wired": "t2", "stat": "t2", "endpoints news": "t2", "endpoints": "t2",
    "coindesk": "t2", "information": "t2", "politico": "t2", "axios": "t2",
    "defense news": "t2", "spacenews": "t2", "space news": "t2", "ieee spectrum": "t2",
}

# ── Legacy rows (pre-breakdown) ───────────────────────────────────────────────
# Rollup rows written before `by_company_breakdown` existed carry only raw `by_company`
# counts; the per-mention impact/tier is unrecoverable (the source articles are pruned
# past the feed window — the very reason weights are folded at read time, not baked in,
# so a true backfill isn't possible). We therefore weight a legacy mention NEUTRALLY
# rather than guessing a default bucket: 1.0 sits mid-scale (≈ contextual × t2), so old
# rows are neither inflated nor penalised. The resulting skew vs newer (weighted) rows is
# transient — it self-heals as legacy rows age out of the read window. Tune here if you'd
# rather assume a default bucket (e.g. contextual|unknown) for unweighted history.
LEGACY_MENTION_WEIGHT = 1.0


def normalize_impact(value) -> str:
    """Canonical impact label (material/contextual/none); missing/unknown → contextual."""
    v = str(value or "").strip().lower()
    return v if v in IMPACT_WEIGHTS else _DEFAULT_IMPACT


def impact_weight(value) -> float:
    return IMPACT_WEIGHTS[normalize_impact(value)]


def tier_weight(tier) -> float:
    return TIER_WEIGHTS.get(str(tier or DEFAULT_TIER), TIER_WEIGHTS[DEFAULT_TIER])


def _normalize_source(name) -> str:
    """Normalize a free-text `source_name` for tier lookup: lowercase, strip a
    scheme/www/path if it's a URL, drop a leading 'the ', trim punctuation."""
    s = str(name or "").strip().lower()
    if not s:
        return ""
    s = s.split("//")[-1]          # drop scheme (https://)
    if s.startswith("www."):
        s = s[4:]
    s = s.split("/")[0]            # drop any path
    if s.startswith("the "):
        s = s[4:]
    return s.strip(" .,'\"")


def source_tier(name) -> str:
    """Map a free-text `source_name` to a tier label (t1/t2/unknown). Unknown and
    missing sources fall to DEFAULT_TIER. Handles plain names ('Reuters') and
    domain forms ('www.coindesk.com' → coindesk)."""
    s = _normalize_source(name)
    if not s:
        return DEFAULT_TIER
    if s in SOURCE_TIERS:
        return SOURCE_TIERS[s]
    if "." in s:                   # domain → try the second-level label
        label = s.split(".")[0]
        if label in SOURCE_TIERS:
            return SOURCE_TIERS[label]
    return DEFAULT_TIER


def company_bucket_weight(bucket_key: str) -> float:
    """Weight for a `by_company_breakdown` bucket key '<impact>|<tier>'."""
    impact, _, tier = bucket_key.partition("|")
    return impact_weight(impact) * tier_weight(tier)


def article_weight(row: dict) -> float:
    """Significance × source weight for a single (live) article row, from its
    `business_impact` and `source_name`. The article-level analogue of
    `company_bucket_weight` — for the views that count over feed rows rather than
    the rollup breakdown (Pulse, the entity dossier, co-mention / convergence /
    capital). Pure."""
    return impact_weight(row.get("business_impact")) * tier_weight(source_tier(row.get("source_name")))


def weighted_companies_in_row(row: dict) -> Iterator[tuple[str, float]]:
    """Yield (company, weight) contributions for one rollup row. Uses the row's
    `by_company_breakdown` when present; otherwise falls back to its raw `by_company`
    at the neutral `LEGACY_MENTION_WEIGHT` — so pre-migration history still contributes
    (unweighted-equivalent) instead of disappearing. Pure.

    A company with several buckets in a row yields once per bucket; sum to total it."""
    bd = row.get("by_company_breakdown")
    if bd:
        for company, buckets in bd.items():
            for key, n in (buckets or {}).items():
                yield company, float(n or 0) * company_bucket_weight(key)
    else:
        for company, n in (row.get("by_company") or {}).items():
            yield company, float(n or 0) * LEGACY_MENTION_WEIGHT


def weighted_company_counts(rollup_rows: Iterable[dict]) -> Counter:
    """Fold rollup rows into a {company: weighted_count} Counter (float values). Pure."""
    c: Counter = Counter()
    for r in rollup_rows:
        for company, w in weighted_companies_in_row(r):
            c[company] += w
    return c
