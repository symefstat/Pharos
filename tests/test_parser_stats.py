"""Tests for HomeNewsParser drop-stats (ParseStats / parse_with_stats) — all pure."""

import json
from datetime import date, timedelta

from home_news.parser import DROPPED_ITEMS_CAP, HomeNewsParser, ParseStats

P = HomeNewsParser()


def _one(**over):
    base = {"title": "T", "summary": "S", "url": "https://ex.com/a"}
    base.update(over)
    return base


def test_parse_still_returns_items_only():
    # The thin wrapper must keep its original list return type (non-breaking).
    items = P.parse(json.dumps([_one()]), max_age_days=3650)
    assert isinstance(items, list) and len(items) == 1


def test_stats_all_valid():
    raw = json.dumps([_one(url="https://x.com/1"), _one(url="https://x.com/2")])
    items, stats = P.parse_with_stats(raw, max_age_days=3650)
    assert len(items) == 2
    assert stats == ParseStats(received=2, parsed=2)


def test_stats_counts_malformed():
    raw = json.dumps([_one(), {"title": "only title"}, "not-an-object"])
    items, stats = P.parse_with_stats(raw, max_age_days=3650)
    assert stats.received == 3
    assert stats.parsed == 1
    assert stats.dropped_malformed == 2  # missing-fields item + the bare string


def test_stats_counts_dup():
    raw = json.dumps([_one(title="A"), _one(title="B")])  # same url
    items, stats = P.parse_with_stats(raw, max_age_days=3650)
    assert stats.parsed == 1 and stats.dropped_dup == 1


def test_stats_counts_stale():
    old = (date.today() - timedelta(days=40)).isoformat()
    fresh = date.today().isoformat()
    raw = json.dumps([
        _one(url="https://x.com/old", published_at=old),
        _one(url="https://x.com/new", published_at=fresh),
    ])
    items, stats = P.parse_with_stats(raw, max_age_days=14)
    assert stats.parsed == 1 and stats.dropped_stale == 1 and stats.received == 2


def test_stats_received_counts_raw_array_length():
    # received is what the agent returned, before any validation.
    raw = json.dumps([_one(), {"bad": 1}, {"also": "bad"}])
    _, stats = P.parse_with_stats(raw, max_age_days=3650)
    assert stats.received == 3


def test_to_metrics_shape():
    _, stats = P.parse_with_stats(json.dumps([_one()]), max_age_days=3650)
    m = stats.to_metrics()
    assert set(m) == {"received", "parsed", "dropped_malformed", "dropped_dup",
                      "dropped_stale", "dropped_items"}
    assert m["received"] == 1 and m["parsed"] == 1
    assert m["dropped_items"] == []  # clean run → no identities to ledger


def test_parsed_equals_returned_item_count():
    raw = json.dumps([
        _one(url="https://x.com/1"),
        _one(url="https://x.com/1"),         # dup
        {"title": "x"},                       # malformed
        _one(url="https://x.com/2"),
    ])
    items, stats = P.parse_with_stats(raw, max_age_days=3650)
    assert stats.parsed == len(items) == 2
    assert stats.dropped_dup == 1 and stats.dropped_malformed == 1
    # received accounts for every dropped + parsed item.
    assert stats.received == stats.parsed + stats.dropped_malformed + stats.dropped_dup + stats.dropped_stale


# ── Dropped-item identities (P1 fix 16) — losses must be auditable, not stdout-only ──

def test_dropped_items_records_dup_and_stale_identities():
    old = (date.today() - timedelta(days=40)).isoformat()
    raw = json.dumps([
        _one(url="https://x.com/a", title="Keep"),
        _one(url="https://x.com/a", title="Dup of a"),
        _one(url="https://x.com/old", title="Stale one", published_at=old),
    ])
    _, stats = P.parse_with_stats(raw, max_age_days=14)
    assert stats.dropped_items == [
        {"reason": "dup", "url": "https://x.com/a", "title": "Dup of a"},
        {"reason": "stale", "url": "https://x.com/old", "title": "Stale one"},
    ]


def test_dropped_items_records_malformed_identity_via_drift_keys():
    # A malformed item's identity uses whatever url/title (incl. drift keys)
    # the raw entry carried; entries with neither still get a reason row.
    raw = json.dumps([
        {"headline": "No url or summary"},
        {"link": "https://x.com/nolink", "summary": "s"},  # missing title
        _one(url="https://x.com/ok"),
    ])
    _, stats = P.parse_with_stats(raw, max_age_days=3650)
    assert stats.dropped_malformed == 2
    assert stats.dropped_items == [
        {"reason": "malformed", "title": "No url or summary"},
        {"reason": "malformed", "url": "https://x.com/nolink"},
    ]


def test_dropped_items_handles_non_dict_entries():
    raw = json.dumps([_one(), "not-an-object", 42])
    _, stats = P.parse_with_stats(raw, max_age_days=3650)
    assert stats.dropped_malformed == 2
    reasons = [d["reason"] for d in stats.dropped_items]
    assert reasons == ["malformed", "malformed"]
    # Non-dict garbage stays identifiable via its repr in the title slot.
    assert stats.dropped_items[0]["title"] == "'not-an-object'"
    assert stats.dropped_items[1]["title"] == "42"


def test_dropped_items_capped_but_counters_stay_exact():
    n = DROPPED_ITEMS_CAP + 5
    raw = json.dumps([{"title": f"bad {i}"} for i in range(n)])
    _, stats = P.parse_with_stats(raw, max_age_days=3650)
    assert stats.dropped_malformed == n                      # exact past the cap
    assert len(stats.dropped_items) == DROPPED_ITEMS_CAP     # payload stays small
    assert stats.to_metrics()["dropped_items"] == stats.dropped_items


def test_note_drop_truncates_long_title_and_url():
    stats = ParseStats()
    stats.note_drop("malformed", url="https://x.com/" + "a" * 600, title="t" * 300)
    (ident,) = stats.dropped_items
    assert len(ident["url"]) == 500 and len(ident["title"]) == 200
