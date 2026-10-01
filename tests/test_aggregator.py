"""Tests for PulseAggregator pure helpers + reducers (no network).

The reducers (quick_stats, top_material_stories) take rows and never touch the
DB client, so we construct the aggregator with a sentinel client.
"""

from analytics.aggregator import PulseAggregator, _normalize_url

AGG = PulseAggregator(client=object())  # sentinel — reducers don't use it


class TestNormalizeUrl:
    def test_collapses_scheme_www_host_case_and_trailing_slash(self):
        assert _normalize_url("https://www.EX.com/a/") == _normalize_url("http://ex.com/a")

    def test_drops_tracking_params_and_fragment(self):
        assert _normalize_url("https://ex.com/a?utm_source=1&fbclid=2#frag") == "ex.com/a"

    def test_empty_and_garbage(self):
        assert _normalize_url("") == ""
        assert _normalize_url("not a url") == ""

    def test_distinct_paths_stay_distinct(self):
        assert _normalize_url("https://ex.com/a") != _normalize_url("https://ex.com/b")

    def test_keeps_meaningful_query_params_distinct(self):
        # F1 regression: ?v=A vs ?v=B are distinct stories, not duplicates.
        assert _normalize_url("https://youtube.com/watch?v=A") != \
            _normalize_url("https://youtube.com/watch?v=B")
        # …while a tracking-only difference still collapses.
        assert _normalize_url("https://youtube.com/watch?v=A&utm_source=x") == \
            _normalize_url("https://youtube.com/watch?v=A")


class TestQuickStats:
    def test_counts_total_material_and_sentiment(self):
        rows = [
            {"business_impact": "material", "sentiment": "positive", "_feed_label": "EV"},
            {"business_impact": "contextual", "sentiment": "negative", "_feed_label": "EV"},
            {"business_impact": "material", "sentiment": "positive", "_feed_label": "Chips"},
        ]
        s = AGG.quick_stats(rows)
        assert s["total"] == 3
        assert s["material"] == 2
        assert s["sentiment"] == {"positive": 2, "negative": 1}
        assert s["per_feed"] == {"EV": 2, "Chips": 1}

    def test_normalizes_companies(self):
        rows = [
            {"companies": ["google", "DeepMind"]},  # both -> Alphabet (Google)
            {"companies": ["Nvidia"]},
        ]
        top = dict(AGG.quick_stats(rows)["top_companies"])
        assert top.get("Alphabet (Google)") == 2
        assert top.get("Nvidia") == 1

    def test_top_companies_weighted_reflects_significance_and_source(self):
        from analytics.weights import IMPACT_WEIGHTS as IW, TIER_WEIGHTS as TW, source_tier
        rows = [
            # Nvidia: one material story from a tier-1 source.
            {"companies": ["Nvidia"], "business_impact": "material", "source_name": "Reuters"},
            # Tesla: two 'none' stories from an unknown source — more mentions, less weight.
            {"companies": ["Tesla"], "business_impact": "none", "source_name": "Some Blog"},
            {"companies": ["Tesla"], "business_impact": "none", "source_name": "Some Blog"},
        ]
        s = AGG.quick_stats(rows)
        assert dict(s["top_companies"]) == {"Nvidia": 1, "Tesla": 2}      # raw: Tesla leads
        w = dict(s["top_companies_weighted"])
        assert source_tier("Reuters") == "t1"
        assert w["Nvidia"] == round(IW["material"] * TW["t1"], 1)         # 4.5
        assert w["Tesla"] == round(2 * IW["none"] * TW["unknown"], 1)     # 0.35
        assert w["Nvidia"] > w["Tesla"]                                   # weighted: Nvidia leads


class TestTopMaterialStories:
    def test_backfills_contextual_then_sorts_by_date(self):
        # Material is the primary set; contextual backfills remaining slots; the
        # combined list is then presented newest-first (chronological).
        rows = [
            {"business_impact": "contextual", "published_at": "2026-06-10", "title": "c"},
            {"business_impact": "material", "published_at": "2026-06-09", "title": "m"},
        ]
        out = AGG.top_material_stories(rows, limit=5)
        assert {r["title"] for r in out} == {"m", "c"}          # both included
        assert [r["title"] for r in out] == ["c", "m"]          # sorted by date desc

    def test_material_excludes_none_impact(self):
        rows = [
            {"business_impact": "material", "published_at": "2026-06-01", "title": "m"},
            {"business_impact": "none", "published_at": "2026-06-09", "title": "n"},
        ]
        # 'none' is neither material nor contextual, so it is never surfaced.
        assert [r["title"] for r in AGG.top_material_stories(rows, limit=5)] == ["m"]

    def test_respects_limit(self):
        rows = [
            {"business_impact": "material", "published_at": f"2026-06-{d:02d}", "title": str(d)}
            for d in range(1, 10)
        ]
        assert len(AGG.top_material_stories(rows, limit=3)) == 3
