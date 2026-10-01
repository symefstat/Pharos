"""Tests for the thesis-watch loop's pure core (analytics.thesis_watch):
building the watch set from the private thesis book, labeled evidence matching
(confirmer → "confirms", falsifier → "falsifies"), idempotent new-event
filtering, and the distinct 🧭 webhook body. Plus persist() idempotency against
a fake Supabase client. No network."""

from types import SimpleNamespace

from analytics.thesis_watch import (
    ThesisWatch,
    _is_missing_table_error,
    format_thesis_alerts,
    match_thesis_evidence,
    new_thesis_events,
    watch_rows,
)

_THESIS = {
    "id": 1,
    "claim": "European stablecoin rails consolidate around MiCA-licensed issuers",
    "falsifier": "Tether gains MiCA authorization by Q4 2026",
    "confirmer": "Circle expands EURC issuance under its MiCA license",
    "created_at": "2026-07-01T09:00:00Z",
    "archived": False,
}


# ── watch_rows ─────────────────────────────────────────────────────────────────

def test_watch_rows_one_row_per_direction_with_labels():
    rows = watch_rows([_THESIS])
    assert [(r["thesis_id"], r["label"]) for r in rows] == [(1, "falsifies"), (1, "confirms")]
    assert rows[0]["text"] == _THESIS["falsifier"]
    assert rows[1]["text"] == _THESIS["confirmer"]
    assert all(r["made_on"] == "2026-07-01" for r in rows)  # date part of created_at


def test_watch_rows_skips_archived_and_blank_texts():
    theses = [
        dict(_THESIS, id=2, archived=True),                      # archived → out
        {"id": 3, "claim": "x", "falsifier": "  ", "confirmer": None,
         "created_at": "2026-07-01T00:00:00Z", "archived": False},  # nothing to watch
        {"id": 4, "claim": "y", "falsifier": "OpenAI releases GPT-6 by 2027",
         "confirmer": None, "created_at": "2026-07-01T00:00:00Z", "archived": False},
    ]
    rows = watch_rows(theses)
    assert [(r["thesis_id"], r["label"]) for r in rows] == [(4, "falsifies")]


def test_watch_rows_empty_input():
    assert watch_rows([]) == []
    assert watch_rows(None) == []


# ── match_thesis_evidence — the event labeling ────────────────────────────────

_FALSIFYING_ARTICLE = {
    "title": "Tether receives MiCA authorization from EU regulator",
    "summary": "The stablecoin issuer cleared the EU's MiCA regime.",
    "url": "https://x/tether-mica", "published_at": "2026-07-07",
}
_CONFIRMING_ARTICLE = {
    "title": "Circle expands EURC issuance under MiCA license",
    "summary": "The issuer widens its euro stablecoin footprint.",
    "url": "https://x/circle-eurc", "published_at": "2026-07-07",
}
_UNRELATED_ARTICLE = {
    "title": "TSMC ramps 2nm production ahead of schedule",
    "summary": "Chip output grows.", "url": "https://x/tsmc-2nm",
    "published_at": "2026-07-07",
}


def test_falsifier_match_is_labeled_falsifies():
    events = match_thesis_evidence([_THESIS], [_FALSIFYING_ARTICLE, _UNRELATED_ARTICLE])
    assert len(events) == 1
    e = events[0]
    assert e["label"] == "falsifies"
    assert e["thesis_id"] == 1
    assert e["matched"] == _THESIS["falsifier"]
    assert e["article_url"] == "https://x/tether-mica"
    assert 0 < e["score"] <= 1


def test_confirmer_match_is_labeled_confirms():
    events = match_thesis_evidence([_THESIS], [_CONFIRMING_ARTICLE, _UNRELATED_ARTICLE])
    assert len(events) == 1
    e = events[0]
    assert e["label"] == "confirms"
    assert e["matched"] == _THESIS["confirmer"]
    assert e["article_url"] == "https://x/circle-eurc"


def test_both_directions_matched_and_sorted_by_score():
    events = match_thesis_evidence(
        [_THESIS], [_FALSIFYING_ARTICLE, _CONFIRMING_ARTICLE, _UNRELATED_ARTICLE])
    assert {e["label"] for e in events} == {"falsifies", "confirms"}
    assert [e["score"] for e in events] == sorted(
        (e["score"] for e in events), reverse=True)


def test_evidence_cannot_predate_thesis_registration():
    old = dict(_FALSIFYING_ARTICLE, published_at="2026-06-15", url="https://x/old")
    assert match_thesis_evidence([_THESIS], [old]) == []


def test_archived_thesis_produces_no_events():
    archived = dict(_THESIS, archived=True)
    assert match_thesis_evidence([archived], [_FALSIFYING_ARTICLE]) == []


# ── new_thesis_events (idempotency) ────────────────────────────────────────────

def test_new_thesis_events_filters_already_persisted_pairs():
    events = [
        {"thesis_id": 1, "article_url": "https://x/a", "score": 0.8},
        {"thesis_id": 1, "article_url": "https://x/b", "score": 0.7},
        {"thesis_id": 2, "article_url": "https://x/a", "score": 0.6},  # same url, other thesis
    ]
    fresh = new_thesis_events(events, {(1, "https://x/a")})
    assert [(e["thesis_id"], e["article_url"]) for e in fresh] == \
        [(1, "https://x/b"), (2, "https://x/a")]


def test_new_thesis_events_dedupes_within_batch_and_skips_incomplete():
    events = [
        {"thesis_id": 1, "article_url": "https://x/a", "score": 0.9, "label": "falsifies"},
        {"thesis_id": 1, "article_url": "https://x/a", "score": 0.6, "label": "confirms"},
        {"thesis_id": None, "article_url": "https://x/a"},
        {"thesis_id": 3, "article_url": None},
    ]
    fresh = new_thesis_events(events, set())
    assert len(fresh) == 1 and fresh[0]["label"] == "falsifies"  # best score wins


# ── formatting + missing-table detection ──────────────────────────────────────

def test_format_thesis_alerts_distinct_prefix_and_labels():
    out = format_thesis_alerts([
        {"label": "confirms", "matched": "Circle expands EURC issuance under its MiCA license",
         "article_title": "Circle expands EURC issuance under MiCA license",
         "article_url": "https://x/circle-eurc"},
        {"label": "falsifies", "matched": "Tether gains MiCA authorization by Q4 2026",
         "article_title": "Tether receives MiCA authorization from EU regulator",
         "article_url": "https://x/tether-mica"},
    ], as_of="2026-07-08 06:00 UTC")
    assert "🧭 Thesis watch (2)" in out and "2026-07-08 06:00 UTC" in out
    assert "🧭 Thesis evidence (confirms): 'Circle expands EURC issuance" in out
    assert "🧭 Thesis evidence (falsifies): 'Tether gains MiCA authorization" in out
    assert "candidate evidence" in out          # never phrased as a verdict
    assert "⚠" not in out                       # can't be confused with falsifier alerts
    assert format_thesis_alerts([]) == ""


def test_is_missing_table_error_specific_signatures_only():
    assert _is_missing_table_error(Exception('relation "public.theses" does not exist'))
    assert _is_missing_table_error(Exception(
        "Could not find the table 'public.thesis_events' in the schema cache (PGRST205)"))
    # other tables / generic failures must NOT be mistaken for a pending migration
    assert not _is_missing_table_error(Exception('relation "predictions" does not exist'))
    assert not _is_missing_table_error(Exception("thesis_events: connection timeout"))


# ── persist() idempotency against a fake client ───────────────────────────────

class _FakeEventsQuery:
    def __init__(self, sb):
        self._sb = sb
        self._mode = "select"
        self._payload = None

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def in_(self, *_a, **_k):
        return self

    def upsert(self, payload, **_k):
        self._mode = "upsert"
        self._payload = list(payload)
        return self

    def execute(self):
        if self._mode == "upsert":
            for row in self._payload:
                key = (row["thesis_id"], row["article_url"])
                if key not in {(r["thesis_id"], r["article_url"]) for r in self._sb.rows}:
                    self._sb.rows.append(dict(row))
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[dict(r) for r in self._sb.rows])


class FakeEventsSupabase:
    def __init__(self):
        self.rows = []

    def table(self, name):
        assert name == "thesis_events"
        return _FakeEventsQuery(self)


def test_persist_is_idempotent_second_run_returns_nothing_new():
    sb = FakeEventsSupabase()
    watch = ThesisWatch(client=sb)
    events = [{"thesis_id": 1, "matched": "t", "label": "falsifies",
               "article_url": "https://x/a", "article_title": "A",
               "published_at": "2026-07-07", "score": 0.8}]
    assert [e["article_url"] for e in watch.persist(events)] == ["https://x/a"]
    assert watch.persist(events) == []          # already persisted → nothing new
    assert len(sb.rows) == 1


def test_persist_degrades_to_empty_when_table_missing():
    class MissingTableSupabase:
        def table(self, name):
            raise Exception('relation "public.thesis_events" does not exist')

    watch = ThesisWatch(client=MissingTableSupabase())
    assert watch.persist([{"thesis_id": 1, "article_url": "https://x/a"}]) == []
