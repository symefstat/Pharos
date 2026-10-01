"""Tests for the pure rollup helpers (analytics/rollup.py): cross-feed dedup and
per-day metric building. No DB — inputs are plain dict rows."""

from analytics.rollup import _count_company_breakdown, build_rows, dedup_by_feed
from analytics.weights import DEFAULT_TIER

_NOW = "2026-06-14T00:00:00+00:00"


# ── dedup_by_feed ──────────────────────────────────────────────────────────────

def test_dedup_first_feed_wins_across_feeds():
    # The same story syndicated into ev and chips is kept only under ev (first).
    feed_rows = [
        ("ev", [{"url": "https://example.com/story", "companies": ["Tesla"]}]),
        ("chips", [{"url": "https://example.com/story", "companies": ["Tesla"]}]),
    ]
    out = dedup_by_feed(feed_rows)
    assert len(out["ev"]) == 1
    assert out["chips"] == []  # dropped — already counted under ev


def test_dedup_normalizes_url_variants():
    # http/https, www, trailing slash, and tracking-param/fragment noise all
    # collapse to one key.
    feed_rows = [
        ("ev", [{"url": "http://www.example.com/a/?utm_source=x#top"}]),
        ("chips", [{"url": "https://example.com/a"}]),
    ]
    out = dedup_by_feed(feed_rows)
    assert len(out["ev"]) == 1 and out["chips"] == []


def test_dedup_keeps_query_distinct_urls():
    # F1 regression: stories keyed on a meaningful query param must NOT merge.
    feed_rows = [
        ("ev", [{"url": "https://youtube.com/watch?v=A"}]),
        ("chips", [{"url": "https://youtube.com/watch?v=B"}]),
    ]
    out = dedup_by_feed(feed_rows)
    assert len(out["ev"]) == 1 and len(out["chips"]) == 1


def test_dedup_keeps_distinct_urls():
    feed_rows = [
        ("ev", [{"url": "https://example.com/a"}]),
        ("chips", [{"url": "https://example.com/b"}]),
    ]
    out = dedup_by_feed(feed_rows)
    assert len(out["ev"]) == 1 and len(out["chips"]) == 1


def test_dedup_keeps_url_less_rows():
    # URL-less rows can't be deduped → always kept, never collapsed together.
    feed_rows = [
        ("ev", [{"url": "", "title": "no url 1"}, {"title": "no url 2"}]),
    ]
    out = dedup_by_feed(feed_rows)
    assert len(out["ev"]) == 2


def test_dedup_drops_intrafeed_duplicate():
    feed_rows = [
        ("ev", [{"url": "https://example.com/a"}, {"url": "https://example.com/a/"}]),
    ]
    out = dedup_by_feed(feed_rows)
    assert len(out["ev"]) == 1  # second occurrence dropped


# ── build_rows ───────────────────────────────────────────────────────────────

def _rows():
    return [
        {"published_at": "2026-06-10", "tags": ["launch"], "sentiment": "positive",
         "business_impact": "material", "scope": "deal", "companies": ["Tesla"], "country": "US"},
        {"published_at": "2026-06-10", "tags": ["launch", "sales"], "sentiment": "positive",
         "business_impact": "contextual", "scope": "sector", "companies": ["Tesla", "BYD"], "country": "US"},
        {"published_at": "2026-06-11", "tags": ["policy"], "sentiment": "neutral",
         "business_impact": "none", "scope": "regulatory", "companies": [], "country": "DE"},
    ]


def test_build_rows_buckets_by_day_and_counts():
    out = build_rows("ev", _rows(), _NOW)
    by_day = {r["metric_date"]: r for r in out}
    assert set(by_day) == {"2026-06-10", "2026-06-11"}
    d10 = by_day["2026-06-10"]
    assert d10["feed"] == "ev"
    assert d10["total_articles"] == 2
    assert d10["by_tag"] == {"launch": 2, "sales": 1}
    assert d10["by_company"] == {"Tesla": 2, "BYD": 1}
    assert d10["by_sentiment"] == {"positive": 2}
    assert d10["by_impact"] == {"material": 1, "contextual": 1}
    assert d10["updated_at"] == _NOW


def test_build_rows_skips_undated_rows():
    rows = [{"published_at": None, "companies": ["X"]},
            {"published_at": "bad", "companies": ["Y"]},
            {"published_at": "2026-06-10", "companies": ["Z"]}]
    out = build_rows("ev", rows, _NOW)
    assert len(out) == 1 and out[0]["metric_date"] == "2026-06-10"


def test_build_rows_empty():
    assert build_rows("ev", [], _NOW) == []


def test_build_rows_emits_company_breakdown():
    out = build_rows("ev", _rows(), _NOW)
    d10 = next(r for r in out if r["metric_date"] == "2026-06-10")
    t = DEFAULT_TIER
    # Tesla: material (item 1) + contextual (item 2); BYD: contextual (item 2).
    assert d10["by_company_breakdown"]["Tesla"] == {f"material|{t}": 1, f"contextual|{t}": 1}
    assert d10["by_company_breakdown"]["BYD"] == {f"contextual|{t}": 1}


# ── _count_company_breakdown ───────────────────────────────────────────────────

def test_count_company_breakdown_splits_by_impact_and_defaults():
    t = DEFAULT_TIER
    items = [
        {"business_impact": "material", "companies": ["Tesla", "BYD"]},
        {"business_impact": "contextual", "companies": ["Tesla"]},
        {"business_impact": None, "companies": ["Tesla"]},      # missing → contextual
        {"business_impact": "bogus", "companies": ["BYD"]},     # invalid → contextual
    ]
    bd = _count_company_breakdown(items)
    assert bd["Tesla"] == {f"material|{t}": 1, f"contextual|{t}": 2}
    assert bd["BYD"] == {f"material|{t}": 1, f"contextual|{t}": 1}


def test_count_company_breakdown_uses_source_tier():
    # source_name resolves to a tier in the bucket key (Reuters → t1, unknown → default).
    items = [
        {"business_impact": "material", "source_name": "Reuters", "companies": ["Nvidia"]},
        {"business_impact": "material", "source_name": "Some Blog", "companies": ["Nvidia"]},
    ]
    bd = _count_company_breakdown(items)
    assert bd["Nvidia"] == {"material|t1": 1, f"material|{DEFAULT_TIER}": 1}


def test_dedup_then_build_counts_entity_once():
    # End-to-end: a story syndicated across feeds must count Tesla once overall.
    feed_rows = [
        ("ev", [{"url": "https://x.com/s", "published_at": "2026-06-10", "companies": ["Tesla"]}]),
        ("chips", [{"url": "https://x.com/s", "published_at": "2026-06-10", "companies": ["Tesla"]}]),
    ]
    survivors = dedup_by_feed(feed_rows)
    ev = build_rows("ev", survivors["ev"], _NOW)
    chips = build_rows("chips", survivors["chips"], _NOW)
    ev_tesla = ev[0]["by_company"].get("Tesla", 0)
    chips_tesla = chips[0]["by_company"].get("Tesla", 0) if chips else 0
    assert ev_tesla + chips_tesla == 1
