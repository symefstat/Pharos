"""Tests for event clustering (pure)."""

from analytics.events import cluster_events, _signature, _jaccard


def test_signature_drops_stopwords_and_short_tokens():
    sig = _signature("Samsung Foundry signs Nvidia cooperation for 4nm chips")
    assert "samsung" in sig and "nvidia" in sig and "4nm" in sig and "foundry" in sig
    assert "for" not in sig and "a" not in sig


def test_merges_same_story_across_outlets():
    rows = [
        {"title": "Samsung Foundry signs Nvidia cooperation for 4nm chips",
         "source_name": "iNews24", "_feed_label": "Chips", "business_impact": "material",
         "summary": "long summary " * 5},
        {"title": "Samsung, Nvidia ink 4nm foundry cooperation deal",
         "source_name": "Reuters", "_feed_label": "Chips", "summary": "short"},
        {"title": "Tesla recalls 12,000 vehicles over brake software",
         "source_name": "AP", "_feed_label": "EV"},
    ]
    events = cluster_events(rows)
    assert len(events) == 2                      # the two Samsung/Nvidia stories merged
    top = events[0]
    assert top["count"] == 2
    assert set(top["sources"]) == {"iNews24", "Reuters"}
    assert top["rep"]["source_name"] == "iNews24"  # material + fuller summary wins


def test_distinct_stories_stay_separate():
    rows = [
        {"title": "Nvidia unveils Blackwell GPU architecture", "source_name": "A"},
        {"title": "Pfizer reports positive phase 3 trial for new drug", "source_name": "B"},
    ]
    events = cluster_events(rows)
    assert len(events) == 2 and all(e["count"] == 1 for e in events)


def test_empty():
    assert cluster_events([]) == []


def test_jaccard():
    assert _jaccard(frozenset("ab"), frozenset("ab")) == 1.0
    assert _jaccard(frozenset(), frozenset("a")) == 0.0


def test_multi_source_count_counts_distinct_outlets_not_stories():
    # A cluster of two rewrites from ONE outlet (count 2, one source) is a single-source
    # duplicate, not corroboration; only clusters spanning >1 outlet count.
    from analytics.events import multi_source_count
    events = [
        {"count": 2, "sources": ["Reuters"]},                 # one outlet → NOT multi-source
        {"count": 2, "sources": ["Reuters", "Bloomberg"]},    # two outlets → multi-source
        {"count": 1, "sources": ["FT"]},                      # single story
    ]
    assert multi_source_count(events) == 1
