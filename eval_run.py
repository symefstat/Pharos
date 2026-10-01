#!/usr/bin/env python3
"""
Eval harness CLI — score the pipeline against the gold set.

The gold set (eval/gold_labels.jsonl) is hand-labelled; see eval/README.md. This
script loads it, gathers the pipeline's predictions, and prints a scorecard
(per-field accuracy + confusion, extraction completeness/provenance, and — live —
a rollup-integrity recompute-and-diff).

Prediction sources:
  --validate-gold              just check the gold file for typos/dupes; no scoring
  --from-fixture PATH          score against a JSONL of prediction rows (offline;
                               used by CI and tests — no DB, no agent calls)
  --from-supabase              join gold urls to the live feed tables (needs DB
                               creds — confirm before running)

All scoring is pure (eval/scoring.py); this file only does I/O + argument plumbing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from eval.gold import GoldLabel, load_gold, read_jsonl, validate
from eval.scoring import render_scorecard, rollup_integrity, score_all

DEFAULT_GOLD = "eval/gold_labels.jsonl"

# How RollupBuilder reads each feed table — the eval must read the same way (same
# order + cap) or the integrity recompute diffs against a different row window than
# the stored rollup was built from, and reports spurious DIFFs.
_FEED_READ_LIMIT = 1000


def _load_fixture(path: str) -> dict[str, dict]:
    """Read a JSONL of prediction rows into {url: row}. Each row is a dict with a
    `url` and any of maturity_stage/adoption_stage/business_impact/scope/provenance."""
    preds: dict[str, dict] = {}
    for row in read_jsonl(path):
        url = str(row.get("url") or "").strip()
        if url:
            preds[url] = row
    return preds


def _gather_supabase(gold: list[GoldLabel], feed_filter: str | None) -> tuple[dict[str, dict], dict[str, dict]]:
    """Read the feed tables (same order+limit RollupBuilder uses) and derive both:
    the gold→prediction join ({url: row}, filtered to the gold urls) and the
    per-feed rollup-integrity diff. Needs Supabase creds.

    ALL feeds are read up front (even under --feed), because the stored rollup is
    built from cross-feed-deduped rows (first-feed-wins, FEEDS order) — so the
    integrity recompute must apply the same `dedup_by_feed` or it diffs against a
    row set the rollup was never built from. The gold/prediction join uses the full
    (pre-dedup) rows: a deduped-away row still carries a valid prediction.

    Returns (preds_by_url, rollup_by_feed)."""
    from db import get_supabase
    from feeds import FEEDS
    from analytics.rollup import dedup_by_feed

    client = get_supabase()
    wanted = {lab.url for lab in gold if lab.url}
    preds: dict[str, dict] = {}

    # Read every feed once (FEEDS order) so the dedup sees the full picture.
    feed_rows_by_key: dict[str, list[dict]] = {}
    for feed in FEEDS:
        try:
            feed_rows_by_key[feed.key] = (
                client.table(feed.table).select("*")
                .order("published_at", desc=True).limit(_FEED_READ_LIMIT)
                .execute().data or []
            )
        except Exception as e:
            print(f"warn: could not read {feed.table}: {e}", file=sys.stderr)
            feed_rows_by_key[feed.key] = []

    survivors = dedup_by_feed([(f.key, feed_rows_by_key[f.key]) for f in FEEDS])

    rollup_by_feed: dict[str, dict] = {}
    for feed in FEEDS:
        if feed_filter and feed.key != feed_filter:
            continue
        # Predictions: full rows by url (dedup doesn't change a row's extracted fields).
        for r in feed_rows_by_key[feed.key]:
            if r.get("url") in wanted:
                preds[r["url"]] = r
        try:
            stored = (
                client.table("feed_daily_metrics")
                .select("*").eq("feed", feed.key).execute().data or []
            )
        except Exception as e:
            print(f"warn: rollup check skipped for {feed.key}: {e}", file=sys.stderr)
            continue
        # Integrity: recompute from the SAME deduped survivors the rollup is built from.
        rollup_by_feed[feed.key] = rollup_integrity(survivors[feed.key], stored)
    return preds, rollup_by_feed


def main() -> int:
    ap = argparse.ArgumentParser(description="Score the pipeline against the gold set.")
    ap.add_argument("--gold", default=DEFAULT_GOLD, help=f"gold JSONL (default: {DEFAULT_GOLD})")
    ap.add_argument("--validate-gold", action="store_true", help="validate the gold file and exit")
    ap.add_argument("--from-fixture", metavar="PATH", help="score against a JSONL of prediction rows (offline)")
    ap.add_argument("--from-supabase", action="store_true", help="join gold to the live feed tables (needs DB creds)")
    ap.add_argument("--feed", help="limit the live read/rollup check to one feed key")
    ap.add_argument("--json", action="store_true", help="emit the scorecard as JSON instead of text")
    args = ap.parse_args()

    try:
        gold = load_gold(args.gold)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: could not load gold set: {e}", file=sys.stderr)
        if isinstance(e, FileNotFoundError):
            print("Label eval/gold_labels.jsonl first — see eval/README.md.", file=sys.stderr)
        return 1

    problems = validate(gold)
    if args.validate_gold:
        if problems:
            print(f"{len(problems)} problem(s) in {args.gold}:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"{args.gold}: {len(gold)} labels, no problems.")
        return 0
    if problems:
        print(f"warn: {len(problems)} gold problem(s) — run --validate-gold to list them.", file=sys.stderr)

    # Gather predictions (and, live, the per-feed rollup-integrity diff).
    rollup_by_feed: dict[str, dict] = {}
    if args.from_fixture:
        preds = _load_fixture(args.from_fixture)
    elif args.from_supabase:
        preds, rollup_by_feed = _gather_supabase(gold, args.feed)
    else:
        print("error: pick a prediction source: --from-fixture PATH or --from-supabase "
              "(or --validate-gold).", file=sys.stderr)
        return 2

    scorecard = score_all(gold, preds)

    if args.json:
        print(json.dumps({"scorecard": scorecard, "rollup": rollup_by_feed}, indent=2))
        return 0

    print(render_scorecard(scorecard, rollup_by_feed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
