"""
Eval scoring — pure functions that grade the pipeline's output against the gold
set and against itself.

  accuracy / score_all       — per-field accuracy + confusion of lens/extraction
                               labels vs the gold set (the "did it get better?" metric)
  completeness               — how often each field actually got a value
  provenance_breakdown       — agent/keydrift/default/missing mix from the audit trail
  recompute_rollup / rollup_integrity
                             — recompute feed_daily_metrics from the feed rows and
                               diff against what's stored (the "is the rollup honest?" check)

Everything here is pure: inputs are plain lists/dicts (gold labels + prediction
rows + rollup rows), outputs are plain dicts. The CLI (eval_run.py) supplies the
I/O. The rollup recompute imports the production counters from analytics.rollup so
it can't diverge from how the rollup is actually built.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from eval.gold import GOLD_FIELDS, GoldLabel, normalize_label

# Reuse the exact counters RollupBuilder uses (build_rows) — recomputing with the
# same code is the only way the integrity diff is meaningful.
from analytics.rollup import (
    _count_companies, _count_company_breakdown, _count_list, _count_scalar,
)

# Metrics RollupBuilder.build_rows writes per (feed, metric_date). Must cover
# EVERY metric build_rows writes — `by_company_breakdown` is what all the
# weighted views (Share of Voice, weighted top companies, entity picker/dossier)
# read, so a corrupted breakdown must not pass the integrity check.
_ROLLUP_METRICS = (
    "total_articles", "by_tag", "by_company", "by_company_breakdown",
    "by_country", "by_sentiment", "by_impact", "by_scope",
)


def accuracy(gold_labels: Iterable[GoldLabel], preds_by_url: dict[str, dict],
             field: str) -> dict:
    """Score one field against gold by joining on url. Only gold rows that labelled
    `field` are counted; a gold url with no matching prediction is tallied as
    `missing_pred` (not a wrong answer). Predictions are normalised the same way
    the gold is, so casing/underscore drift doesn't read as a miss.

    Returns {field, n, correct, accuracy, missing_pred, confusion} where confusion
    is {true_label: {predicted_label: count}} ('<none>' = no value predicted)."""
    correct = 0
    n = 0
    missing_pred = 0
    confusion: dict[str, dict[str, int]] = {}
    for lab in gold_labels:
        true = getattr(lab, field)
        if true is None:
            continue
        pred_row = preds_by_url.get(lab.url)
        if pred_row is None:
            missing_pred += 1
            continue
        pred = normalize_label(pred_row.get(field))
        n += 1
        bucket = confusion.setdefault(true, {})
        key = pred if pred is not None else "<none>"
        bucket[key] = bucket.get(key, 0) + 1
        if pred == true:
            correct += 1
    return {
        "field": field,
        "n": n,
        "correct": correct,
        "accuracy": (correct / n) if n else None,
        "missing_pred": missing_pred,
        "confusion": confusion,
    }


def completeness(rows: Sequence[dict], fields: Sequence[str] = GOLD_FIELDS) -> dict:
    """Per field, the share of `rows` that carry a non-empty value. A data-quality
    metric independent of gold — measures how often the pipeline produced anything
    at all for each field."""
    total = len(rows)
    out: dict[str, dict] = {}
    for f in fields:
        present = sum(1 for r in rows if str(r.get(f) or "").strip())
        out[f] = {
            "present": present,
            "total": total,
            "coverage": (present / total) if total else None,
        }
    return out


def provenance_breakdown(rows: Sequence[dict]) -> dict:
    """Aggregate the per-field extraction provenance (agent/keydrift/default/missing)
    across rows that carry a `provenance` dict. Rows predating the provenance column
    are skipped. Returns {field: {how: count}}."""
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        prov = r.get("provenance")
        if not isinstance(prov, dict):
            continue
        for field, how in prov.items():
            bucket = out.setdefault(field, {})
            bucket[str(how)] = bucket.get(str(how), 0) + 1
    return out


def score_all(gold_labels: Sequence[GoldLabel], preds_by_url: dict[str, dict],
              fields: Sequence[str] = GOLD_FIELDS) -> dict:
    """Assemble the per-field scorecard: accuracy/confusion vs gold (joined on url),
    plus completeness + provenance over the supplied prediction set. Note the live
    CLI only fetches gold-matched rows, so completeness there describes the scored
    subset, not the whole feed."""
    all_preds = list(preds_by_url.values())
    joined = sum(1 for lab in gold_labels if lab.url in preds_by_url)
    return {
        "gold_total": len(gold_labels),
        "preds_total": len(preds_by_url),
        "joined": joined,
        "accuracy": {f: accuracy(gold_labels, preds_by_url, f) for f in fields},
        "completeness": completeness(all_preds, fields),
        "provenance": provenance_breakdown(all_preds),
    }


def recompute_rollup(feed_rows: Sequence[dict]) -> dict[str, dict]:
    """Recompute the per-day rollup metrics from feed rows, mirroring
    RollupBuilder.build_rows exactly. Callers pass cross-feed-deduped rows (see
    dedup_by_feed) so this matches the stored rollup. Returns {metric_date:
    {metric: value}}. Pure."""
    by_day: dict[str, list[dict]] = {}
    for r in feed_rows:
        d = str(r.get("published_at") or "")[:10]
        if len(d) == 10:
            by_day.setdefault(d, []).append(r)
    return {
        d: {
            "total_articles": len(items),
            "by_tag": _count_list(items, "tags"),
            "by_company": _count_companies(items),
            "by_company_breakdown": _count_company_breakdown(items),
            "by_country": _count_scalar(items, "country", lower=False),
            "by_sentiment": _count_scalar(items, "sentiment"),
            "by_impact": _count_scalar(items, "business_impact"),
            "by_scope": _count_scalar(items, "scope"),
        }
        for d, items in by_day.items()
    }


def rollup_integrity(feed_rows: Sequence[dict],
                     stored_rollup_rows: Sequence[dict]) -> dict:
    """Recompute the rollup from the (still-present) feed rows and diff it against
    what's stored in feed_daily_metrics. Only days present in the feed table are
    checked — older days have been pruned from the feed and can't be re-verified.

    Returns {days_checked, clean, diffs} where each diff names the day, the metric,
    and the recomputed-vs-stored values (or flags a day missing from the rollup)."""
    recomputed = recompute_rollup(feed_rows)
    stored_by_day = {str(r.get("metric_date"))[:10]: r for r in stored_rollup_rows}
    diffs: list[dict] = []
    for d in sorted(recomputed):
        rec = recomputed[d]
        stored = stored_by_day.get(d)
        if stored is None:
            diffs.append({"metric_date": d, "metric": "*", "issue": "missing_from_rollup"})
            continue
        for m in _ROLLUP_METRICS:
            if rec[m] != stored.get(m):
                diffs.append({
                    "metric_date": d, "metric": m,
                    "recomputed": rec[m], "stored": stored.get(m),
                })
    return {"days_checked": len(recomputed), "clean": not diffs, "diffs": diffs}


def _pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def render_scorecard(scorecard: dict, rollup_by_feed: Optional[dict] = None) -> str:
    """Render a scorecard (and optional per-feed rollup-integrity results) as a
    readable text block. Pure — takes the dicts score_all returns and a
    {feed_key: rollup_integrity(...)} map. The single place scorecard text is
    formatted, so the CLI never re-implements it."""
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("Lodestar eval scorecard")
    lines.append("=" * 64)
    lines.append(
        f"gold labels: {scorecard['gold_total']}   "
        f"predictions: {scorecard['preds_total']}   "
        f"joined on url: {scorecard['joined']}"
    )

    lines.append("")
    lines.append("Per-field accuracy (vs gold):")
    for field, a in scorecard["accuracy"].items():
        miss = f"  ({a['missing_pred']} gold rows had no prediction)" if a["missing_pred"] else ""
        lines.append(f"  {field:16s} {_pct(a['accuracy'])}  (n={a['n']}, correct={a['correct']}){miss}")
        for true in sorted(a["confusion"]):
            preds = a["confusion"][true]
            wrong = {p: c for p, c in preds.items() if p != true}
            if wrong:
                wrong_str = ", ".join(f"{p}×{c}" for p, c in sorted(wrong.items()))
                lines.append(f"      {true} → {wrong_str}")

    lines.append("")
    lines.append("Extraction completeness (share of scored predictions with a value):")
    for field, c in scorecard["completeness"].items():
        lines.append(f"  {field:16s} {_pct(c['coverage'])}  ({c['present']}/{c['total']})")

    if scorecard["provenance"]:
        lines.append("")
        lines.append("Extraction provenance (how each field was obtained):")
        for field in sorted(scorecard["provenance"]):
            mix = scorecard["provenance"][field]
            mix_str = ", ".join(f"{how}×{n}" for how, n in sorted(mix.items()))
            lines.append(f"  {field:16s} {mix_str}")

    for feed_key, result in (rollup_by_feed or {}).items():
        lines.append("")
        status = "CLEAN" if result["clean"] else f"{len(result['diffs'])} DIFFS"
        lines.append(f"Rollup integrity [{feed_key}]: {status}  ({result['days_checked']} days checked)")
        for d in result["diffs"][:20]:
            if d.get("issue"):
                lines.append(f"  {d['metric_date']}  {d['metric']}: {d['issue']}")
            else:
                lines.append(f"  {d['metric_date']}  {d['metric']}: recomputed={d['recomputed']} stored={d['stored']}")

    lines.append("=" * 64)
    return "\n".join(lines)


def render_ab(label_a: str, sc_a: dict, label_b: str, sc_b: dict) -> str:
    """Render a side-by-side A/B of two scorecards (e.g. lens prompt v1 vs v2) as a
    readable table: per-field accuracy for each, the delta in percentage points, and
    the join counts. Pure — takes the dicts score_all returns. Fields are the union
    of both scorecards' scored fields. A field with no comparable n shows 'n/a'."""
    # Union of both scorecards' scored fields (sc_a's order first, then any sc_b extras).
    fields = list(dict.fromkeys([*sc_a.get("accuracy", {}), *sc_b.get("accuracy", {})]))
    lines = [
        "=" * 64,
        f"Lens A/B — {label_a} vs {label_b}",
        "=" * 64,
        f"{label_a}: {sc_a.get('joined', 0)} joined   {label_b}: {sc_b.get('joined', 0)} joined",
        "",
        f"{'field':16s} {label_a:>10s} {label_b:>10s} {'Δ (pp)':>10s}   {'n':>5s}",
    ]
    for f in fields:
        a = sc_a.get("accuracy", {}).get(f, {})
        b = sc_b.get("accuracy", {}).get(f, {})
        acc_a, acc_b = a.get("accuracy"), b.get("accuracy")
        delta = (
            f"{(acc_b - acc_a) * 100:+6.1f}"
            if isinstance(acc_a, (int, float)) and isinstance(acc_b, (int, float)) else "   n/a"
        )
        # n is the head-to-head sample (gold rows both versions answered for this field).
        n = min(a.get("n", 0), b.get("n", 0))
        lines.append(f"{f:16s} {_pct(acc_a):>10s} {_pct(acc_b):>10s} {delta:>10s}   {n:>5d}")
    lines.append("=" * 64)
    return "\n".join(lines)
