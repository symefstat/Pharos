"""Tests for the falsifier alert loop's pure core (analytics.falsifier_watch):
extracting the watch set, keyword evidence matching, idempotent new-event
filtering, and the webhook body. No network, no Supabase."""

from analytics.falsifier_watch import (
    _is_missing_table_error,
    format_falsifier_alerts,
    match_evidence,
    new_events,
    open_falsifiers,
)


# ── open_falsifiers ────────────────────────────────────────────────────────────

def test_open_falsifiers_extracts_only_open_manual_with_falsifier():
    preds = [
        {"id": 1, "status": "open", "kind": "manual", "claim": "Stablecoins consolidate — wrong if: Tether gains MiCA authorization by Q4 2026",
         "params": {"falsifier": "Tether gains MiCA authorization by Q4 2026"}, "made_on": "2026-07-01"},
        {"id": 2, "status": "resolved", "kind": "manual",
         "params": {"falsifier": "resolved — must not appear"}},          # already graded
        {"id": 3, "status": "open", "kind": "stage_advance",
         "params": {"falsifier": "auto kind — must not appear"}},          # not a judgment call
        {"id": 4, "status": "open", "kind": "manual", "params": {}},       # no falsifier
        {"id": 5, "status": "open", "kind": "manual", "params": {"falsifier": "  "}},  # blank
    ]
    rows = open_falsifiers(preds)
    assert [r["pred_id"] for r in rows] == [1]
    assert rows[0]["falsifier"] == "Tether gains MiCA authorization by Q4 2026"
    assert rows[0]["made_on"] == "2026-07-01"
    assert "wrong if" in rows[0]["claim"]


def test_open_falsifiers_empty_input():
    assert open_falsifiers([]) == []
    assert open_falsifiers(None) == []


# ── match_evidence ─────────────────────────────────────────────────────────────

_TETHER_ROW = {"pred_id": 1, "claim": "Stablecoins consolidate",
               "falsifier": "Tether gains MiCA authorization by Q4 2026",
               "made_on": "2026-07-01"}


def test_match_evidence_hits_the_disproving_article_not_the_chips_one():
    articles = [
        {"title": "Tether receives MiCA authorization from EU regulator",
         "summary": "The stablecoin issuer cleared the EU's MiCA regime.",
         "url": "https://x/tether-mica", "published_at": "2026-07-07"},
        {"title": "TSMC ramps 2nm production ahead of schedule",
         "summary": "Chip output grows.", "url": "https://x/tsmc-2nm",
         "published_at": "2026-07-07"},
    ]
    matches = match_evidence([_TETHER_ROW], articles)
    assert len(matches) == 1
    m = matches[0]
    assert m["pred_id"] == 1
    assert m["article_url"] == "https://x/tether-mica"
    assert m["falsifier"] == _TETHER_ROW["falsifier"]
    assert m["published_at"] == "2026-07-07"
    assert 0 < m["score"] <= 1


def test_match_evidence_one_shared_name_is_not_evidence():
    # A single overlapping entity token must never trigger (min 2 hits).
    row = {"pred_id": 2, "falsifier": "OpenAI releases GPT-6 by 2027"}
    articles = [{"title": "OpenAI hires a new CFO", "summary": "Leadership change.",
                 "url": "https://x/openai-cfo", "published_at": "2026-07-07"}]
    assert match_evidence([row], articles) == []


def test_match_evidence_threshold_and_ordering():
    row = {"pred_id": 1, "falsifier": "Tether gains MiCA authorization by Q4 2026"}
    strong = {"title": "Tether gains MiCA authorization in 2026", "summary": "",
              "url": "https://x/strong", "published_at": "2026-07-07"}
    weak = {"title": "Tether volume report", "summary": "MiCA mentioned in passing.",
            "url": "https://x/weak", "published_at": "2026-07-07"}
    # weak: 2 hits of 5 tokens = 0.4 — passes min-hits but not the 0.5 threshold
    assert [m["article_url"] for m in match_evidence([row], [strong, weak])] == ["https://x/strong"]
    # lowering the threshold admits it, ranked below the strong match
    urls = [m["article_url"] for m in match_evidence([row], [strong, weak], threshold=0.3)]
    assert urls == ["https://x/strong", "https://x/weak"]


def test_match_evidence_skips_articles_predating_the_call():
    articles = [{"title": "Tether receives MiCA authorization from EU regulator",
                 "summary": "", "url": "https://x/old", "published_at": "2026-06-15"}]
    assert match_evidence([_TETHER_ROW], articles) == []       # before made_on 2026-07-01
    undated = dict(articles[0], published_at=None, url="https://x/undated")
    assert len(match_evidence([_TETHER_ROW], [undated])) == 1  # undated ⇒ not excluded


def test_match_evidence_empty_inputs():
    assert match_evidence([], [{"title": "x"}]) == []
    assert match_evidence([_TETHER_ROW], []) == []
    assert match_evidence([{"pred_id": 9, "falsifier": ""}], [{"title": "x"}]) == []


# ── new_events (idempotency) ───────────────────────────────────────────────────

def test_new_events_filters_already_persisted_pairs():
    events = [
        {"pred_id": 1, "article_url": "https://x/a", "score": 0.8},
        {"pred_id": 1, "article_url": "https://x/b", "score": 0.7},
        {"pred_id": 2, "article_url": "https://x/a", "score": 0.6},  # same url, other forecast
    ]
    existing = {(1, "https://x/a")}
    fresh = new_events(events, existing)
    assert [(e["pred_id"], e["article_url"]) for e in fresh] == \
        [(1, "https://x/b"), (2, "https://x/a")]


def test_new_events_dedupes_within_batch_and_skips_incomplete():
    events = [
        {"pred_id": 1, "article_url": "https://x/a", "score": 0.9},  # vector hit
        {"pred_id": 1, "article_url": "https://x/a", "score": 0.6},  # keyword found it too
        {"pred_id": None, "article_url": "https://x/a"},             # no forecast id
        {"pred_id": 3, "article_url": None},                          # no url
    ]
    fresh = new_events(events, set())
    assert len(fresh) == 1 and fresh[0]["score"] == 0.9


# ── formatting + missing-table detection ──────────────────────────────────────

def test_format_falsifier_alerts():
    out = format_falsifier_alerts([
        {"falsifier": "Tether gains MiCA authorization by Q4 2026",
         "article_title": "Tether receives MiCA authorization from EU regulator",
         "article_url": "https://x/tether-mica"},
    ], as_of="2026-07-08 06:00 UTC")
    assert "Falsifier watch (1)" in out and "2026-07-08 06:00 UTC" in out
    assert "⚠ Falsifier evidence: 'Tether gains MiCA authorization by Q4 2026' may have triggered" in out
    assert "Tether receives MiCA authorization from EU regulator (https://x/tether-mica)" in out
    assert "candidate evidence" in out          # never phrased as a resolution
    assert format_falsifier_alerts([]) == ""


def test_is_missing_table_error_specific_signatures_only():
    assert _is_missing_table_error(Exception('relation "public.falsifier_events" does not exist'))
    assert _is_missing_table_error(Exception(
        "Could not find the table 'public.falsifier_events' in the schema cache (PGRST205)"))
    # other tables / generic failures must NOT be mistaken for a pending migration
    assert not _is_missing_table_error(Exception('relation "predictions" does not exist'))
    assert not _is_missing_table_error(Exception("falsifier_events: connection timeout"))
