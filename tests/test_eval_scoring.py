"""Tests for the pure eval scoring functions (eval/scoring.py)."""

from eval.gold import label_from_dict
from eval.scoring import (
    accuracy, completeness, provenance_breakdown, recompute_rollup,
    render_ab, render_scorecard, rollup_integrity, score_all,
)


def _gold(rows):
    return [label_from_dict(r) for r in rows]


# ── accuracy ─────────────────────────────────────────────────────────────────

def test_accuracy_correct_and_wrong_build_confusion():
    gold = _gold([
        {"url": "a", "maturity_stage": "emerging"},
        {"url": "b", "maturity_stage": "growth"},
    ])
    preds = {
        "a": {"maturity_stage": "emerging"},        # correct
        "b": {"maturity_stage": "dominant-design"}, # wrong (boundary slip)
    }
    r = accuracy(gold, preds, "maturity_stage")
    assert r["n"] == 2 and r["correct"] == 1 and r["accuracy"] == 0.5
    assert r["missing_pred"] == 0
    assert r["confusion"] == {"emerging": {"emerging": 1}, "growth": {"dominant-design": 1}}


def test_accuracy_missing_prediction_not_a_miss():
    gold = _gold([{"url": "a", "scope": "deal"}, {"url": "b", "scope": "sector"}])
    preds = {"a": {"scope": "deal"}}  # b has no prediction row
    r = accuracy(gold, preds, "scope")
    assert r["n"] == 1 and r["correct"] == 1 and r["missing_pred"] == 1


def test_accuracy_skips_unlabelled_gold_field():
    gold = _gold([{"url": "a", "scope": "deal"}])  # maturity not labelled
    preds = {"a": {"maturity_stage": "growth", "scope": "deal"}}
    r = accuracy(gold, preds, "maturity_stage")
    assert r["n"] == 0 and r["accuracy"] is None


def test_accuracy_normalises_prediction():
    gold = _gold([{"url": "a", "maturity_stage": "dominant-design"}])
    preds = {"a": {"maturity_stage": "Dominant_Design"}}  # casing + underscore
    assert accuracy(gold, preds, "maturity_stage")["correct"] == 1


def test_accuracy_none_prediction_bucketed():
    gold = _gold([{"url": "a", "maturity_stage": "growth"}])
    preds = {"a": {"maturity_stage": None}}
    r = accuracy(gold, preds, "maturity_stage")
    assert r["correct"] == 0 and r["confusion"] == {"growth": {"<none>": 1}}


# ── completeness / provenance ────────────────────────────────────────────────

def test_completeness():
    rows = [{"scope": "deal"}, {"scope": ""}, {"scope": "sector"}]
    c = completeness(rows, ["scope"])["scope"]
    assert c == {"present": 2, "total": 3, "coverage": 2 / 3}


def test_completeness_empty():
    assert completeness([], ["scope"])["scope"]["coverage"] is None


def test_provenance_breakdown():
    rows = [
        {"provenance": {"scope": "agent", "business_impact": "default"}},
        {"provenance": {"scope": "agent", "business_impact": "agent"}},
        {"provenance": None},  # predates the column — skipped
    ]
    out = provenance_breakdown(rows)
    assert out["scope"] == {"agent": 2}
    assert out["business_impact"] == {"default": 1, "agent": 1}


# ── score_all ────────────────────────────────────────────────────────────────

def test_score_all_shape():
    gold = _gold([{"url": "a", "maturity_stage": "growth", "scope": "deal"}])
    preds = {"a": {"maturity_stage": "growth", "scope": "deal"}}
    sc = score_all(gold, preds)
    assert sc["gold_total"] == 1 and sc["preds_total"] == 1 and sc["joined"] == 1
    assert set(sc["accuracy"]) == {"maturity_stage", "adoption_stage", "business_impact", "scope"}
    assert sc["accuracy"]["maturity_stage"]["accuracy"] == 1.0


# ── rollup recompute + integrity ─────────────────────────────────────────────

def _feed_rows():
    return [
        {"published_at": "2026-06-10", "tags": ["launch"], "sentiment": "positive",
         "business_impact": "material", "scope": "deal", "companies": ["Tesla"], "country": "US"},
        {"published_at": "2026-06-10", "tags": ["launch", "sales"], "sentiment": "positive",
         "business_impact": "contextual", "scope": "sector", "companies": ["Tesla"], "country": "US"},
        {"published_at": "2026-06-11", "tags": ["policy"], "sentiment": "neutral",
         "business_impact": "none", "scope": "regulatory", "companies": [], "country": "DE"},
    ]


def test_recompute_rollup_counts():
    rec = recompute_rollup(_feed_rows())
    assert set(rec) == {"2026-06-10", "2026-06-11"}
    d10 = rec["2026-06-10"]
    assert d10["total_articles"] == 2
    assert d10["by_tag"] == {"launch": 2, "sales": 1}
    assert d10["by_sentiment"] == {"positive": 2}
    assert d10["by_impact"] == {"material": 1, "contextual": 1}


def test_recompute_rollup_includes_company_breakdown():
    # F3 regression: the recompute must cover by_company_breakdown — the field
    # every weighted view reads — using the production counter (impact|tier buckets).
    rec = recompute_rollup(_feed_rows())
    assert rec["2026-06-10"]["by_company_breakdown"] == {
        "Tesla": {"material|unknown": 1, "contextual|unknown": 1},
    }
    assert rec["2026-06-11"]["by_company_breakdown"] == {}


def test_rollup_integrity_clean():
    rows = _feed_rows()
    rec = recompute_rollup(rows)
    stored = [{"metric_date": d, **m} for d, m in rec.items()]
    result = rollup_integrity(rows, stored)
    assert result["clean"] is True and result["diffs"] == []
    assert result["days_checked"] == 2


def test_rollup_integrity_detects_drift():
    rows = _feed_rows()
    rec = recompute_rollup(rows)
    stored = [{"metric_date": d, **m} for d, m in rec.items()]
    stored[0]["total_articles"] = 99  # corrupt one stored value
    result = rollup_integrity(rows, stored)
    assert result["clean"] is False
    assert any(d["metric"] == "total_articles" and d["stored"] == 99 for d in result["diffs"])


def test_rollup_integrity_detects_breakdown_drift():
    # F3 regression: a corrupted by_company_breakdown must fail the check — it
    # used to pass clean because _ROLLUP_METRICS omitted the field.
    rows = _feed_rows()
    rec = recompute_rollup(rows)
    stored = [{"metric_date": d, **m} for d, m in rec.items()]
    day = next(s for s in stored if s["metric_date"] == "2026-06-10")
    day["by_company_breakdown"] = {"Tesla": {"none|unknown": 999}}
    result = rollup_integrity(rows, stored)
    assert result["clean"] is False
    assert any(d["metric"] == "by_company_breakdown" and d["metric_date"] == "2026-06-10"
               for d in result["diffs"])


def test_rollup_integrity_breakdown_key_order_insensitive():
    # JSONB round-trips don't guarantee key order — a stored breakdown with the
    # same content in a different (nested) key order must still compare clean.
    rows = _feed_rows()
    rec = recompute_rollup(rows)
    stored = []
    for d, m in rec.items():
        m = dict(m)
        m["by_company_breakdown"] = {
            company: dict(reversed(list(buckets.items())))
            for company, buckets in reversed(list(m["by_company_breakdown"].items()))
        }
        stored.append({"metric_date": d, **m})
    result = rollup_integrity(rows, stored)
    assert result["clean"] is True and result["diffs"] == []


def test_rollup_integrity_flags_day_missing_from_rollup():
    rows = _feed_rows()
    result = rollup_integrity(rows, [])  # nothing stored at all
    issues = [d for d in result["diffs"] if d.get("issue") == "missing_from_rollup"]
    assert {d["metric_date"] for d in issues} == {"2026-06-10", "2026-06-11"}


def test_rollup_integrity_ignores_pruned_days():
    # A day in the stored rollup but absent from the (pruned) feed rows must NOT
    # be flagged — we can't re-verify it, and it's legitimately retained history.
    rows = _feed_rows()
    rec = recompute_rollup(rows)
    stored = [{"metric_date": d, **m} for d, m in rec.items()]
    stored.append({"metric_date": "2026-01-01", "total_articles": 5, "by_tag": {},
                   "by_company": {}, "by_country": {}, "by_sentiment": {},
                   "by_impact": {}, "by_scope": {}})
    result = rollup_integrity(rows, stored)
    assert result["clean"] is True  # the old pruned day is ignored


# ── render ───────────────────────────────────────────────────────────────────

def test_render_scorecard_runs():
    gold = _gold([{"url": "a", "maturity_stage": "growth"}])
    preds = {"a": {"maturity_stage": "emerging", "provenance": {"scope": "agent"}}}
    text = render_scorecard(score_all(gold, preds))
    assert "Lodestar eval scorecard" in text
    assert "maturity_stage" in text


def test_render_scorecard_with_rollup():
    gold = _gold([{"url": "a", "scope": "deal"}])
    preds = {"a": {"scope": "deal"}}
    rollup_by_feed = {"ev": {"days_checked": 1, "clean": False,
                             "diffs": [{"metric_date": "2026-06-10", "metric": "total_articles",
                                        "recomputed": 2, "stored": 99}]}}
    text = render_scorecard(score_all(gold, preds), rollup_by_feed)
    assert "Rollup integrity [ev]: 1 DIFFS" in text
    assert "total_articles: recomputed=2 stored=99" in text


def test_render_ab_shows_per_field_delta():
    gold = _gold([{"url": "a", "maturity_stage": "growth"},
                  {"url": "b", "maturity_stage": "emerging"}])
    v1 = {"a": {"maturity_stage": "growth"}, "b": {"maturity_stage": "growth"}}   # 1/2
    v2 = {"a": {"maturity_stage": "growth"}, "b": {"maturity_stage": "emerging"}}  # 2/2
    sc1 = score_all(gold, v1, ("maturity_stage",))
    sc2 = score_all(gold, v2, ("maturity_stage",))
    out = render_ab("v1", sc1, "v2", sc2)
    assert "maturity_stage" in out
    assert "+50.0" in out          # 50% -> 100% = +50.0pp
    assert "v1" in out and "v2" in out


def test_render_ab_handles_missing_field_gracefully():
    gold = _gold([{"url": "a", "maturity_stage": "growth"}])
    sc1 = score_all(gold, {"a": {"maturity_stage": "growth"}}, ("maturity_stage",))
    sc2 = score_all(gold, {}, ("maturity_stage",))   # v2 has no predictions
    out = render_ab("v1", sc1, "v2", sc2)
    line = next(l for l in out.splitlines() if l.startswith("maturity_stage"))
    assert "100.0%" in line        # v1 was scored
    assert "n/a" in line           # v2 had no answer → delta degrades to n/a, no crash


def test_render_ab_unions_fields_from_both():
    gold = _gold([{"url": "a", "maturity_stage": "growth", "adoption_stage": "early-majority"}])
    sc_a = score_all(gold, {"a": {"maturity_stage": "growth"}}, ("maturity_stage",))
    sc_b = score_all(gold, {"a": {"adoption_stage": "early-majority"}}, ("adoption_stage",))
    out = render_ab("a", sc_a, "b", sc_b)
    # a field only B scored must still appear (true union, not sc_a-only)
    assert "maturity_stage" in out and "adoption_stage" in out


def test_render_scorecard_multiple_feeds_clean():
    gold = _gold([{"url": "a", "scope": "deal"}])
    preds = {"a": {"scope": "deal"}}
    rollup_by_feed = {"ev": {"days_checked": 3, "clean": True, "diffs": []},
                      "chips": {"days_checked": 1, "clean": True, "diffs": []}}
    text = render_scorecard(score_all(gold, preds), rollup_by_feed)
    assert "Rollup integrity [ev]: CLEAN" in text
    assert "Rollup integrity [chips]: CLEAN" in text
