"""Tests for the API data layer's TTL cache — specifically the stale-serving
guarantee (H2): a warm refresh that comes back empty (Supabase blip) must never
replace good cached data, or an outage renders as blank-but-200 pages."""

from backend.app.data import _TTLCache


def test_set_keep_good_keeps_previous_on_empty():
    c = _TTLCache()
    c.set("rows:30", [{"id": 1}])
    c.set_keep_good("rows:30", [])  # outage: loader degraded to empty
    assert c.get_or_set("rows:30", ttl=300, producer=lambda: "MISS") == [{"id": 1}]


def test_set_keep_good_restamps_ttl_of_kept_value():
    c = _TTLCache()
    c.set("k", [1])
    # simulate the entry being one tick from expiry, then an empty warm refresh
    ts, val = c._store["k"]
    c._store["k"] = (ts - 10_000, val)
    c.set_keep_good("k", [])
    # the kept value must survive with a fresh TTL, not expire mid-outage
    assert c.get_or_set("k", ttl=300, producer=lambda: "MISS") == [1]


def test_set_keep_good_accepts_real_data():
    c = _TTLCache()
    c.set("k", [1])
    c.set_keep_good("k", [2, 3])
    assert c.get_or_set("k", ttl=300, producer=lambda: "MISS") == [2, 3]


def test_set_keep_good_stores_empty_when_nothing_cached():
    # first-ever warm on a fresh instance during an outage: nothing to keep,
    # empty is the honest value (pages show their empty states)
    c = _TTLCache()
    c.set_keep_good("k", [])
    assert c.get_or_set("k", ttl=300, producer=lambda: "MISS") == []
