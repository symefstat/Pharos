"""Tests for HomeNewsParser — all pure (no network)."""

from datetime import date, timedelta

from home_news.parser import HomeNewsParser

P = HomeNewsParser()


def _one(**over):
    base = {"title": "T", "summary": "S", "url": "https://ex.com/a"}
    base.update(over)
    return base


def test_parses_fenced_array():
    raw = '```json\n[{"title":"A","summary":"s","url":"https://x.com/1"}]\n```'
    items = P.parse(raw, max_age_days=3650)
    assert len(items) == 1 and items[0].title == "A"


def test_strips_think_preamble():
    import json
    raw = "<think>reason</think>" + json.dumps([_one()])
    assert len(P.parse(raw, max_age_days=3650)) == 1


def test_wrapper_key_object():
    import json
    raw = json.dumps({"articles": [_one()]})
    assert len(P.parse(raw, max_age_days=3650)) == 1


def test_dedupes_by_url():
    import json
    raw = json.dumps([_one(title="A"), _one(title="B")])  # same url
    items = P.parse(raw, max_age_days=3650)
    assert len(items) == 1


def test_drops_stale_items():
    import json
    old = (date.today() - timedelta(days=40)).isoformat()
    fresh = date.today().isoformat()
    raw = json.dumps([
        _one(url="https://x.com/old", published_at=old),
        _one(url="https://x.com/new", published_at=fresh),
    ])
    items = P.parse(raw, max_age_days=14)
    urls = {i.url for i in items}
    assert urls == {"https://x.com/new"}


def test_http_upgraded_to_https():
    import json
    raw = json.dumps([_one(url="http://ex.com/a")])
    items = P.parse(raw, max_age_days=3650)
    assert items[0].url == "https://ex.com/a"


def test_canonicalize_url_strips_tracking_but_keeps_meaningful_params():
    from home_news.parser import canonicalize_url
    # utm_* / fbclid / #fragment stripped; host lowercased; trailing slash gone;
    # meaningful params (?v=) and path case preserved.
    assert canonicalize_url("https://Ex.com/A/?utm_source=nl&v=B&fbclid=x#frag") == \
        "https://ex.com/A?v=B"
    assert canonicalize_url("https://ex.com/a/") == "https://ex.com/a"
    assert canonicalize_url("https://ex.com/?utm_campaign=x") == "https://ex.com"


def test_stored_url_is_canonical():
    import json
    raw = json.dumps([_one(url="https://X.com/a/?utm_campaign=feed&id=7#top")])
    items = P.parse(raw, max_age_days=3650)
    assert items[0].url == "https://x.com/a?id=7"


def test_dedupes_tracking_param_and_slash_variants():
    import json
    # Live eval found 53 trailing-slash dup rows — these must collapse pre-write.
    raw = json.dumps([
        _one(url="https://x.com/a"),
        _one(url="https://X.com/a/?utm_source=nl"),
    ])
    items = P.parse(raw, max_age_days=3650)
    assert [i.url for i in items] == ["https://x.com/a"]


def test_meaningful_query_params_stay_distinct():
    import json
    # ?v=A vs ?v=B are different stories — must NOT dedupe.
    raw = json.dumps([
        _one(url="https://youtube.com/watch?v=A"),
        _one(url="https://youtube.com/watch?v=B"),
    ])
    assert len(P.parse(raw, max_age_days=3650)) == 2


def test_key_drift_headline_and_link():
    import json
    raw = json.dumps([{"headline": "H", "description": "D", "link": "https://x.com/k"}])
    items = P.parse(raw, max_age_days=3650)
    assert items[0].title == "H" and items[0].summary == "D" and items[0].url == "https://x.com/k"


def test_drops_items_missing_required_fields():
    import json
    raw = json.dumps([{"title": "only title"}, _one(url="https://x.com/ok")])
    items = P.parse(raw, max_age_days=3650)
    assert [i.url for i in items] == ["https://x.com/ok"]


def test_rejects_non_web_url():
    import json
    raw = json.dumps([_one(url="ftp://x.com/a")])
    assert P.parse(raw, max_age_days=3650) == []


def test_business_impact_and_scope_defaults():
    import json
    raw = json.dumps([_one()])  # neither field provided
    item = P.parse(raw, max_age_days=3650)[0]
    assert item.business_impact == "contextual"  # conservative default
    assert item.scope == "single-company"


def test_business_impact_invalid_falls_back_to_default():
    import json
    raw = json.dumps([_one(business_impact="banana", scope="weird")])
    item = P.parse(raw, max_age_days=3650)[0]
    assert item.business_impact == "contextual" and item.scope == "single-company"


def test_companies_deduped_case_insensitively():
    import json
    raw = json.dumps([_one(companies=["Uber", "uber", " Uber "])])
    item = P.parse(raw, max_age_days=3650)[0]
    assert item.companies == ["Uber"]


def test_sentiment_normalized_or_nulled():
    import json
    raw = json.dumps([
        _one(url="https://x.com/1", sentiment="Positive"),
        _one(url="https://x.com/2", sentiment="weird"),
    ])
    items = {i.url: i for i in P.parse(raw, max_age_days=3650)}
    assert items["https://x.com/1"].sentiment == "positive"
    assert items["https://x.com/2"].sentiment is None


def test_provenance_marks_agent_default_and_missing():
    import json
    raw = json.dumps([_one(
        business_impact="material", scope="deal", sentiment="positive",
        companies=["Nvidia"], source_name="Reuters", published_at="2026-06-10",
        # country omitted → missing
    )])
    p = P.parse(raw, max_age_days=3650)[0].provenance
    assert p["business_impact"] == "agent" and p["scope"] == "agent"
    assert p["sentiment"] == "agent" and p["companies"] == "agent"
    assert p["source_name"] == "agent" and p["published_at"] == "agent"
    assert p["country"] == "missing"
    assert p["title"] == "agent" and p["url"] == "agent"
    assert p["tags"] == "missing"  # omitted → tracked like every other field


def test_provenance_marks_keydrift_and_defaults():
    import json
    # title via 'headline', url via 'link', source via 'source', date via 'date';
    # business_impact/scope omitted → default; sentiment invalid → missing.
    raw = json.dumps([{"headline": "H", "summary": "S", "link": "https://x.com/k",
                       "source": "Bloomberg", "date": "2026-06-10", "sentiment": "weird"}])
    p = P.parse(raw, max_age_days=3650)[0].provenance
    assert p["title"] == "keydrift" and p["url"] == "keydrift"
    assert p["source_name"] == "keydrift" and p["published_at"] == "keydrift"
    assert p["business_impact"] == "default" and p["scope"] == "default"
    assert p["sentiment"] == "missing" and p["companies"] == "missing"


def test_tags_provenance_agent_keydrift_and_missing():
    import json
    # tags was the one agent field without a provenance entry (eval Bug 6) —
    # it must now mirror _build_item's tags/categories/category resolution.
    raw = json.dumps([
        _one(url="https://x.com/1", tags=["ev", "policy"]),
        _one(url="https://x.com/2", categories=["chips"]),
        _one(url="https://x.com/3", category="energy"),
        _one(url="https://x.com/4"),
    ])
    items = {i.url: i for i in P.parse(raw, max_age_days=3650)}
    assert items["https://x.com/1"].provenance["tags"] == "agent"
    assert items["https://x.com/1"].tags == ["ev", "policy"]
    assert items["https://x.com/2"].provenance["tags"] == "keydrift"
    assert items["https://x.com/2"].tags == ["chips"]
    assert items["https://x.com/3"].provenance["tags"] == "keydrift"
    assert items["https://x.com/3"].tags == ["energy"]
    assert items["https://x.com/4"].provenance["tags"] == "missing"
    assert items["https://x.com/4"].tags == []


def test_provenance_covers_every_agent_derived_field():
    import json
    # Guard against the next "one field forgot provenance" regression: every
    # signal-bearing field stored by to_row() must carry a provenance marker
    # (image_url is writer-derived, provenance is the trail itself).
    item = P.parse(json.dumps([_one()]), max_age_days=3650)[0]
    agent_fields = set(item.to_row()) - {"image_url", "provenance"}
    assert agent_fields <= set(item.provenance)


def test_provenance_in_to_row():
    import json
    item = P.parse(json.dumps([_one()]), max_age_days=3650)[0]
    assert isinstance(item.to_row()["provenance"], dict)
    assert item.to_row()["provenance"]["business_impact"] == "default"
