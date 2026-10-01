"""Tests for the pure lens batch reconciliation (reconcile_batch / LensRunStats)
and the per-feed error capture in run_with_stats. No Supabase — only the
index-matching + normalisation + returned-flag + error-surfacing logic."""

from analytics.lens import LensClassifier, LensRunStats, reconcile_batch


def _rows(*urls):
    return [{"url": u, "title": "t", "summary": "s"} for u in urls]


def test_all_returned_normalised():
    rows = _rows("a", "b")
    by_index = {
        0: {"index": 0, "maturity_stage": "Growth", "adoption_stage": "early-majority",
            "strategic_move": "platform", "rationale": "  because  "},
        1: {"index": 1, "maturity_stage": "dominant_design", "adoption_stage": "laggards",
            "strategic_move": "disruption", "rationale": ""},
    }
    out = reconcile_batch(rows, by_index)
    assert [r[0] for r in out] == ["a", "b"]
    assert all(returned for _, _, returned in out)
    # underscore→hyphen + lowercase normalisation, rationale stripped / empty→None,
    # no echoed prompt_version → None (caller stamps the deployed constant)
    assert out[0][1] == {"maturity_stage": "growth", "adoption_stage": "early-majority",
                         "strategic_move": "platform", "lens_rationale": "because",
                         "lens_prompt_version": None}
    assert out[1][1]["maturity_stage"] == "dominant-design"
    assert out[1][1]["lens_rationale"] is None


def test_missing_index_falls_back_and_flags_not_returned():
    rows = _rows("a", "b")
    by_index = {0: {"index": 0, "maturity_stage": "growth"}}  # row 1 omitted
    out = reconcile_batch(rows, by_index)
    url0, fields0, returned0 = out[0]
    url1, fields1, returned1 = out[1]
    assert returned0 is True and returned1 is False
    # the omitted row gets the conservative fallbacks (today's behaviour)
    assert fields1 == {"maturity_stage": "n/a", "adoption_stage": "n/a",
                       "strategic_move": "none", "lens_rationale": None,
                       "lens_prompt_version": None}


def test_invalid_values_fall_back_to_defaults():
    rows = _rows("a")
    out = reconcile_batch(rows, {0: {"maturity_stage": "banana",
                                     "adoption_stage": "nonsense",
                                     "strategic_move": "wat"}})
    _, fields, returned = out[0]
    assert returned is True  # the agent did return this index
    assert fields["maturity_stage"] == "n/a"
    assert fields["adoption_stage"] == "n/a"
    assert fields["strategic_move"] == "none"


def test_empty_batch():
    assert reconcile_batch([], {}) == []


def test_lens_run_stats_to_metrics():
    s = LensRunStats(requested=10, returned=7, written=6, batches=2)
    assert s.to_metrics() == {"requested": 10, "returned": 7, "written": 6,
                              "missing": 3, "batches": 2}


def test_lens_run_stats_default_zero():
    assert LensRunStats().to_metrics() == {"requested": 0, "returned": 0, "written": 0,
                                           "missing": 0, "batches": 0}


def test_reconcile_extracts_echoed_prompt_version():
    out = reconcile_batch([{"url": "a"}], {0: {"maturity_stage": "growth",
                                               "prompt_version": "mot-lens-v2"}})
    assert out[0][1]["lens_prompt_version"] == "mot-lens-v2"
    # absent → None (caller stamps the deployed constant)
    out2 = reconcile_batch([{"url": "b"}], {0: {"maturity_stage": "growth"}})
    assert out2[0][1]["lens_prompt_version"] is None


# ── classify_feed_with_stats version stamping (fake update-capturing client) ──

class _FakeUpdate:
    def __init__(self, parent, row):
        self.parent = parent
        self.row = row

    def eq(self, col, val):
        return self

    def execute(self):
        self.parent.calls += 1
        # Model a missing column: any update carrying lens_prompt_version fails.
        if self.parent.fail_version and "lens_prompt_version" in self.row:
            raise Exception(
                "Could not find the 'lens_prompt_version' column of 't' in the schema cache")
        self.parent.updates.append(dict(self.row))
        return type("Resp", (), {"data": [{}]})()


class _FakeUpdateClient:
    def __init__(self, fail_version=False):
        self.updates = []
        self.calls = 0
        self.fail_version = fail_version

    def table(self, name):
        return type("T", (), {"update": lambda _s, row: _FakeUpdate(self, row)})()


_FAKEFEED = type("Feed", (), {"table": "t", "key": "ev"})()


def test_classify_stamps_deployed_version_else_echoed(monkeypatch):
    from analytics import lens as lensmod
    fake = _FakeUpdateClient()
    clf = lensmod.LensClassifier(client=fake)
    rows = [{"url": "a"}, {"url": "b"}]
    monkeypatch.setattr(clf, "_unclassified", lambda table, limit=lensmod.BATCH: rows if fake.calls == 0 else [])
    monkeypatch.setattr(clf, "_classify_batch", lambda r: {
        0: {"maturity_stage": "growth"},                               # not echoed → constant
        1: {"maturity_stage": "emerging", "prompt_version": "mot-lens-v2"},  # echoed wins
    })
    written, _stats = clf.classify_feed_with_stats(_FAKEFEED)
    assert written == 2
    versions = [u["lens_prompt_version"] for u in fake.updates]
    assert versions[0] == lensmod.LENS_PROMPT_VERSION
    assert versions[1] == "mot-lens-v2"


def test_classify_degrades_without_version_column(monkeypatch):
    from analytics import lens as lensmod
    fake = _FakeUpdateClient(fail_version=True)
    clf = lensmod.LensClassifier(client=fake)
    rows = [{"url": "a"}, {"url": "b"}]
    monkeypatch.setattr(clf, "_unclassified", lambda table, limit=lensmod.BATCH: rows if fake.calls == 0 else [])
    monkeypatch.setattr(clf, "_classify_batch", lambda r: {0: {"maturity_stage": "growth"},
                                                           1: {"maturity_stage": "emerging"}})
    written, _stats = clf.classify_feed_with_stats(_FAKEFEED)
    assert written == 2                                            # still classified
    assert all("lens_prompt_version" not in u for u in fake.updates)  # stripped after the miss


def test_classify_in_memory_returns_url_fields_no_write(monkeypatch):
    from analytics import lens as lensmod
    clf = lensmod.LensClassifier(client=object())  # dummy client must never be touched
    rows = [{"url": "a", "title": "t1"}, {"url": "b", "title": "t2"}]
    monkeypatch.setattr(clf, "_classify_batch", lambda batch: {
        i: {"maturity_stage": "growth" if r["url"] == "a" else "emerging"}
        for i, r in enumerate(batch)
    })
    out = clf.classify_in_memory(rows)
    assert set(out) == {"a", "b"}
    assert out["a"]["maturity_stage"] == "growth"
    assert out["b"]["maturity_stage"] == "emerging"
    # fields carry the full normalised lens dict (adoption/move defaulted, version None)
    assert out["a"]["adoption_stage"] == "n/a" and out["a"]["lens_prompt_version"] is None


def _stateful_lens(monkeypatch, pool_urls, classify_fn, batch=8):
    """A LensClassifier whose _unclassified serves NULL rows from `pool_urls` minus
    those already written (so it reflects DB state across iterations), and whose
    client records written urls. `classify_fn(batch) -> by_index` simulates the agent."""
    from analytics import lens as lensmod
    monkeypatch.setattr(lensmod, "BATCH", batch)
    written: list = []

    class _Upd:
        def __init__(self):
            self.url = None

        def eq(self, col, val):
            self.url = val
            return self

        def execute(self):
            written.append(self.url)
            return type("R", (), {"data": [{}]})()

    class _Client:
        def table(self, name):
            return type("T", (), {"update": lambda _s, row: _Upd()})()

    clf = lensmod.LensClassifier(client=_Client())
    calls = {"n": 0}

    def unclassified(table, limit=None):
        lim = limit or batch
        avail = [u for u in pool_urls if u not in written]
        # Real _unclassified has no ORDER BY — simulate unstable order by rotating each
        # call, so the tests prove termination is order-independent (it relies on the
        # `attempted` set, not fetch order).
        rot = calls["n"] % (len(avail) or 1)
        avail = avail[rot:] + avail[:rot]
        calls["n"] += 1
        return [{"url": u, "title": "t"} for u in avail][:lim]

    monkeypatch.setattr(clf, "_unclassified", unclassified)
    monkeypatch.setattr(clf, "_classify_batch", classify_fn)
    return clf, written, calls


def test_classify_leaves_omitted_row_null_writes_rest_and_terminates(monkeypatch):
    # Agent always omits "b"; pool > batch so it spans several iterations.
    def classify(batch):
        return {i: {"maturity_stage": "growth"} for i, r in enumerate(batch) if r["url"] != "b"}

    clf, written, calls = _stateful_lens(monkeypatch, ["a", "b", "c", "d"], classify, batch=2)
    n, stats = clf.classify_feed_with_stats(_FAKEFEED, max_items=100)

    assert set(written) == {"a", "c", "d"}        # the rest are classified
    assert "b" not in written                      # the omitted row is left NULL (not poisoned)
    assert n == 3
    # Ledger is honest: b counts as missing, not a fake n/a; all returned rows persisted.
    assert stats.requested == 4 and stats.returned == 3 and stats.written == 3
    assert stats.to_metrics()["missing"] == 1
    assert calls["n"] <= 6                          # bounded — no spinning


def test_classify_terminates_when_agent_returns_nothing(monkeypatch):
    # The infinite-loop guard: a dead agent (returns nothing) must not spin forever.
    clf, written, calls = _stateful_lens(monkeypatch, ["a", "b", "c", "d"], lambda batch: {}, batch=2)
    n, stats = clf.classify_feed_with_stats(_FAKEFEED, max_items=100)
    assert written == [] and n == 0               # nothing written
    assert calls["n"] <= 6                          # and it TERMINATED (bounded fetches), no hang


def test_run_with_stats_surfaces_per_feed_error(monkeypatch):
    # A feed that raises must come back with an error string (so the ledger can
    # record ok=False) — not be silently indistinguishable from a clean no-op.
    clf = LensClassifier(client=object())  # dummy client; classify is stubbed out

    def fake(feed, max_items=200):
        if feed.key == "ev":
            raise RuntimeError("boom")
        return (3, LensRunStats(requested=3, returned=3, batches=1))

    monkeypatch.setattr(clf, "classify_feed_with_stats", fake)
    out = clf.run_with_stats()

    assert out["ev"] == (0, LensRunStats(), "boom")          # error surfaced
    written, stats, error = out["chips"]
    assert written == 3 and error is None and stats.returned == 3
    # run() still collapses to {feed: written_count}
    assert clf.run() == {k: (0 if k == "ev" else 3) for k in out}
