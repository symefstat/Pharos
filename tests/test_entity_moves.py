"""Tests for competitor move detection (analytics.entity_moves — pure)."""

from analytics.entity_moves import entity_moves, format_move_alerts

SINCE = "2026-07-01T00:00:00+00:00"


def _row(**kw) -> dict:
    base = {
        "title": "Nvidia opens Blackwell platform to partners",
        "url": "u1",
        "_feed_label": "Chips",
        "companies": ["Nvidia"],
        "strategic_move": "platform",
        "published_at": "2026-07-05T10:00:00+00:00",
        "business_impact": "material",
    }
    base.update(kw)
    return base


def test_matches_watched_entity_with_move():
    out = entity_moves([_row()], ["Nvidia"], SINCE)
    assert len(out) == 1
    m = out[0]
    assert m == {
        "entity": "Nvidia",
        "move": "platform",
        "title": "Nvidia opens Blackwell platform to partners",
        "url": "u1",
        "feed": "Chips",
        "published_at": "2026-07-05T10:00:00+00:00",
        "impact": "material",
    }


def test_matching_is_case_insensitive_and_alias_aware():
    # case-insensitive on both sides, even for names the alias map doesn't know
    assert entity_moves([_row(companies=["NVIDIA"])], ["nvidia"], SINCE)
    assert entity_moves([_row(companies=["Zoox"])], ["zoox"], SINCE)
    # alias map: a watched "Google" catches a DeepMind story (same canonical)
    out = entity_moves([_row(companies=["DeepMind"])], ["Google"], SINCE)
    assert len(out) == 1
    assert out[0]["entity"] == "Alphabet (Google)"
    # legal suffixes are stripped, as in the rest of the pipeline
    assert entity_moves([_row(companies=["Nvidia Corp"])], ["Nvidia"], SINCE)


def test_unwatched_and_unmatched_rows_excluded():
    assert entity_moves([_row(companies=["TSMC"])], ["Nvidia"], SINCE) == []
    assert entity_moves([_row()], [], SINCE) == []
    assert entity_moves([], ["Nvidia"], SINCE) == []


def test_since_filter_excludes_old_and_undated_rows():
    old = _row(published_at="2026-06-20T00:00:00+00:00")
    undated = _row(published_at=None)
    fresh = _row()
    out = entity_moves([old, undated, fresh], ["Nvidia"], SINCE)
    assert [m["published_at"] for m in out] == ["2026-07-05T10:00:00+00:00"]


def test_non_classified_rows_excluded():
    # the lens writes "none" for stories without a strategic move; missing /
    # "n/a" mean the same — none of them may alert
    rows = [
        _row(strategic_move="none", url="a"),
        _row(strategic_move=None, url="b"),
        _row(strategic_move="n/a", url="c"),
        _row(strategic_move="  ", url="d"),
        _row(strategic_move="Entry-Timing", url="e"),  # normalized to lowercase
    ]
    out = entity_moves(rows, ["Nvidia"], SINCE)
    assert [(m["move"], m["url"]) for m in out] == [("entry-timing", "e")]


def test_dedupes_on_entity_and_url():
    out = entity_moves([_row(), _row()], ["Nvidia"], SINCE)
    assert len(out) == 1


def test_newest_first():
    rows = [
        _row(url="old", published_at="2026-07-02T00:00:00+00:00"),
        _row(url="new", published_at="2026-07-06T00:00:00+00:00"),
    ]
    out = entity_moves(rows, ["Nvidia"], SINCE)
    assert [m["url"] for m in out] == ["new", "old"]


def test_format_move_alerts():
    out = format_move_alerts([
        {"entity": "Nvidia", "move": "platform",
         "title": "Nvidia opens Blackwell platform", "url": "http://x"},
        {"entity": "BYD", "move": "entry-timing", "title": None, "url": None},
    ])
    lines = out.split("\n")
    assert lines[0] == "🏢 Competitor move: Nvidia — platform · Nvidia opens Blackwell platform (http://x)"
    assert lines[1] == "🏢 Competitor move: BYD — entry-timing"
    assert format_move_alerts([]) == ""
