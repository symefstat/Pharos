"""Tests for the writer's pure helpers — missing-column detection, the pre-write
groundedness check, and the cross-feed dedup guard. No network, no real Supabase:
DB interactions use an in-memory fake client."""

from types import SimpleNamespace

import home_news.writer as writer_mod
from home_news.parser import HomeNewsItem
from home_news.writer import (
    HomeNewsWriter,
    _apply_groundedness,
    _html_to_text,
    _is_missing_column_error,
    groundedness_violations,
)


def _item(**over):
    base = dict(title="T", summary="S", url="https://ex.com/a")
    base.update(over)
    return HomeNewsItem(**base)


def test_detects_missing_provenance_column():
    # PostgREST schema-cache miss (column not in the API schema yet).
    e1 = Exception("Could not find the 'provenance' column of 'fintech_articles' "
                   "in the schema cache (PGRST204)")
    assert _is_missing_column_error(e1, "provenance") is True
    # Postgres undefined-column.
    e2 = Exception('column "provenance" does not exist (42703)')
    assert _is_missing_column_error(e2, "provenance") is True


def test_unrelated_errors_are_not_swallowed():
    # A different failure must propagate (not be mistaken for a missing column).
    assert _is_missing_column_error(Exception("connection reset by peer"), "provenance") is False
    # A constraint/value error that NAMES the provenance column must NOT be mistaken
    # for a missing column — else strip-and-retry would mask the real failure.
    assert _is_missing_column_error(
        Exception('null value in column "provenance" violates not-null constraint'),
        "provenance") is False
    assert _is_missing_column_error(
        Exception("provenance value violates not-null constraint"), "provenance") is False
    # A missing *different* column shouldn't match the provenance check.
    assert _is_missing_column_error(
        Exception("column \"sentiment\" does not exist"), "provenance") is False


# ── Pre-write groundedness check (L2 fix 5) ───────────────────────────────────

class TestGroundedness:
    SOURCE = ("Pattern Energy said the project features 674 of GE Vernova's "
              "workhorse turbines, backed by Stripe and Visa, delivering "
              "approximately 3,650 megawatts.")

    def test_grounded_item_has_no_violations(self):
        item = _item(summary="The project features 674 turbines (3,650 MW).",
                     companies=["Stripe", "Visa"])
        assert groundedness_violations(item, self.SOURCE) == {}

    def test_fabricated_number_flagged(self):
        # Live eval fabrication #2: stored "916 turbines" vs the source's 674.
        item = _item(summary="featuring 916 turbines")
        assert groundedness_violations(item, self.SOURCE) == {"numbers": ["916"]}

    def test_fabricated_entity_flagged(self):
        # Live eval fabrication #1: 'BlackRock' appears 0 times in the source.
        item = _item(companies=["Stripe", "BlackRock"])
        assert groundedness_violations(item, self.SOURCE) == {"companies": ["BlackRock"]}

    def test_comma_grouping_does_not_false_flag(self):
        # "3,650" in the source grounds a summary's "3650" and vice versa.
        item = _item(summary="a 3650 megawatt project")
        assert groundedness_violations(item, self.SOURCE) == {}

    def test_company_match_is_case_insensitive(self):
        item = _item(companies=["stripe", "VISA"])
        assert groundedness_violations(item, self.SOURCE) == {}

    def test_apply_flags_suspect_in_provenance_and_keeps_item(self):
        # Flag, don't drop — consistent with the pipeline's tolerate-and-mark
        # treatment of suspect optional data (e.g. invalid sentiment → null).
        item = _item(summary="916 turbines", companies=["BlackRock"])
        _apply_groundedness(item, "<html><body>674 turbines by Visa</body></html>")
        g = item.provenance["groundedness"]
        assert g["status"] == "suspect"
        assert g["numbers"] == ["916"] and g["companies"] == ["BlackRock"]

    def test_apply_marks_verified_and_preserves_existing_provenance(self):
        item = _item(summary="674 turbines", companies=["Visa"],
                     provenance={"title": "agent"})
        _apply_groundedness(item, "<p>674 turbines by Visa</p>")
        assert item.provenance["groundedness"] == {"status": "verified"}
        assert item.provenance["title"] == "agent"

    def test_unfetchable_source_marks_unverified(self):
        # Paywall/403/timeout is not evidence of fabrication — mark, don't flag.
        item = _item(summary="916 turbines")
        _apply_groundedness(item, None)
        assert item.provenance["groundedness"] == {"status": "unverified"}

    def test_html_to_text_strips_script_and_unescapes(self):
        html = "<script>var x = 999;</script><p>674&nbsp;turbines &amp; Visa</p>"
        text = _html_to_text(html)
        assert "674" in text and "999" not in text and "& Visa" in text


# ── Cross-feed dedup guard (L2 fix 8b) ────────────────────────────────────────

class _FakeTable:
    """Minimal PostgREST stub: select().in_().execute() answers URL lookups from
    `urls`; upsert().execute() records rows into `sink`."""

    def __init__(self, urls, sink):
        self._urls = urls
        self._sink = sink
        self._wanted = None
        self._pending = None

    def select(self, *_a, **_k):
        return self

    def in_(self, _col, values):
        self._wanted = list(values)
        return self

    def upsert(self, rows, on_conflict=None):
        self._pending = rows
        return self

    def execute(self):
        if self._pending is not None:
            self._sink.extend(self._pending)
            return SimpleNamespace(data=self._pending)
        return SimpleNamespace(
            data=[{"url": u} for u in self._urls if u in (self._wanted or [])])


class _FakeSupabase:
    def __init__(self, stored: dict):
        self.stored = stored          # table name -> list of stored URLs
        self.upserted: dict = {}      # table name -> rows written

    def table(self, name):
        return _FakeTable(self.stored.get(name, []), self.upserted.setdefault(name, []))


class _BrokenSupabase:
    def table(self, name):
        raise RuntimeError("db unavailable")


_FAKE_FEEDS = [SimpleNamespace(table="ev_articles"), SimpleNamespace(table="chips_articles")]


class TestCrossFeedDedup:
    def test_drops_url_already_stored_by_another_feed(self, monkeypatch):
        monkeypatch.setattr(writer_mod, "FEEDS", _FAKE_FEEDS)
        fake = _FakeSupabase({"chips_articles": ["https://ex.com/dup"]})
        w = HomeNewsWriter(table="ev_articles", supabase_client=fake)
        items = [_item(url="https://ex.com/dup"), _item(url="https://ex.com/fresh")]
        kept = w._filter_cross_feed_dups(items)
        assert [i.url for i in kept] == ["https://ex.com/fresh"]
        assert w.cross_feed_skipped == 1
        # WHICH urls were skipped is ledgerable, not stdout-only (P1 fix 16).
        assert w.cross_feed_skipped_urls == ["https://ex.com/dup"]

    def test_own_table_rows_do_not_block_reupsert(self, monkeypatch):
        # A URL already in OUR table must survive — on_conflict handles it.
        monkeypatch.setattr(writer_mod, "FEEDS", _FAKE_FEEDS)
        fake = _FakeSupabase({"ev_articles": ["https://ex.com/mine"]})
        w = HomeNewsWriter(table="ev_articles", supabase_client=fake)
        kept = w._filter_cross_feed_dups([_item(url="https://ex.com/mine")])
        assert [i.url for i in kept] == ["https://ex.com/mine"]
        assert w.cross_feed_skipped == 0
        assert w.cross_feed_skipped_urls == []

    def test_read_failure_degrades_to_keeping_everything(self, monkeypatch):
        # Best-effort guard: a broken read must never block the write.
        monkeypatch.setattr(writer_mod, "FEEDS", _FAKE_FEEDS)
        w = HomeNewsWriter(table="ev_articles", supabase_client=_BrokenSupabase())
        items = [_item(url="https://ex.com/a")]
        assert w._filter_cross_feed_dups(items) == items
        assert w.cross_feed_skipped == 0
        assert w.cross_feed_skipped_urls == []

    def test_upsert_applies_guard_before_writing(self, monkeypatch):
        monkeypatch.setattr(writer_mod, "FEEDS", _FAKE_FEEDS)
        monkeypatch.setattr(writer_mod._ImageProxy, "proxy_many",
                            lambda self, items, max_workers=8: None)  # no network
        fake = _FakeSupabase({"chips_articles": ["https://ex.com/dup"]})
        w = HomeNewsWriter(table="ev_articles", supabase_client=fake)
        n = w.upsert([_item(url="https://ex.com/dup"), _item(url="https://ex.com/fresh")])
        assert n == 1
        assert [r["url"] for r in fake.upserted["ev_articles"]] == ["https://ex.com/fresh"]
        assert w.cross_feed_skipped == 1
        assert w.cross_feed_skipped_urls == ["https://ex.com/dup"]

    def test_skipped_urls_capped_but_count_exact(self, monkeypatch):
        from home_news.parser import DROPPED_ITEMS_CAP
        monkeypatch.setattr(writer_mod, "FEEDS", _FAKE_FEEDS)
        n = DROPPED_ITEMS_CAP + 5
        urls = [f"https://ex.com/{i}" for i in range(n)]
        fake = _FakeSupabase({"chips_articles": urls})
        w = HomeNewsWriter(table="ev_articles", supabase_client=fake)
        kept = w._filter_cross_feed_dups([_item(url=u) for u in urls])
        assert kept == []
        assert w.cross_feed_skipped == n                          # exact past the cap
        assert w.cross_feed_skipped_urls == urls[:DROPPED_ITEMS_CAP]

    def test_empty_upsert_resets_skip_accounting(self, monkeypatch):
        # A caller reading the attrs after an empty run must not see the
        # previous batch's skips.
        monkeypatch.setattr(writer_mod, "FEEDS", _FAKE_FEEDS)
        monkeypatch.setattr(writer_mod._ImageProxy, "proxy_many",
                            lambda self, items, max_workers=8: None)  # no network
        fake = _FakeSupabase({"chips_articles": ["https://ex.com/dup"]})
        w = HomeNewsWriter(table="ev_articles", supabase_client=fake)
        w.upsert([_item(url="https://ex.com/dup")])
        assert w.cross_feed_skipped == 1
        assert w.upsert([]) == 0
        assert w.cross_feed_skipped == 0 and w.cross_feed_skipped_urls == []


# ── Prosus tagging at write time ──────────────────────────────────────────────

class TestProsusTagging:
    def _writer(self, monkeypatch, index):
        monkeypatch.setattr(writer_mod, "FEEDS", _FAKE_FEEDS)
        monkeypatch.setattr(writer_mod, "load_alias_index", lambda client: index)
        fake = _FakeSupabase({})
        return HomeNewsWriter(table="ev_articles", supabase_client=fake), fake

    def test_every_row_gets_the_key_even_without_a_match(self, monkeypatch):
        # A mixed batch must not leave prosus_tags absent on non-matching rows:
        # PostgREST null-fills missing keys across a batch, violating NOT NULL.
        from prosus.matcher import build_alias_index
        index = build_alias_index(
            [{"slug": "ifood", "aliases": ["iFood"], "status": "active"}])
        w, fake = self._writer(monkeypatch, index)
        w.upsert([
            _item(url="https://ex.com/hit", title="iFood expands"),
            _item(url="https://ex.com/miss", title="DoorDash stablecoin payouts"),
        ])
        rows = fake.upserted["ev_articles"]
        assert [r["prosus_tags"] for r in rows] == [["ifood"], []]

    def test_no_index_means_no_key_on_any_row(self, monkeypatch):
        # Uniform absence is fine — the whole column is missing from the
        # payload, so the table default applies.
        w, fake = self._writer(monkeypatch, None)
        w.upsert([_item(url="https://ex.com/a", title="iFood expands")])
        assert "prosus_tags" not in fake.upserted["ev_articles"][0]
