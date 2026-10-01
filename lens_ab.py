#!/usr/bin/env python3
"""
A/B the MOT Lens prompt against the gold set — non-destructively.

Scores the *currently deployed* lens prompt (v2) against the labels already stored
in the DB (v1, classified while v1 was deployed), on the hand-labelled gold set:

  v1 baseline  — the maturity/adoption labels already in the feed tables.
  v2 challenger — fresh classifications from the deployed agent, computed IN MEMORY
                  and never written back, so the experiment can't corrupt production.

Only maturity_stage + adoption_stage are scored — they're the fields the lens
produces that the gold set labels (business_impact/scope come from the feed parser,
not the lens; strategic_move isn't in gold).

⚠️ Makes live calls: a Supabase read of the gold articles + Toqan calls to classify
them with the deployed agent. Run only when you mean to.

  ./venv/bin/python lens_ab.py [--gold eval/gold_labels.jsonl] [--feed KEY]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from eval.gold import GoldLabel, load_gold, validate
from eval.scoring import render_ab, score_all

DEFAULT_GOLD = "eval/gold_labels.jsonl"
# The lens produces these; the gold set labels them. (business_impact/scope are the
# feed parser's, not the lens's; strategic_move isn't labelled in gold.)
_LENS_FIELDS = ("maturity_stage", "adoption_stage")


def _read_gold_rows(gold: list[GoldLabel], feed_filter: str | None) -> list[dict]:
    """Fetch the gold articles' rows from the feed tables, joining by url (chunked
    `in_` queries so recency/row-cap can't drop a gold article that exists)."""
    from db import get_supabase
    from feeds import FEEDS

    client = get_supabase()
    wanted = [lab.url for lab in gold if lab.url]
    rows: list[dict] = []
    seen: set[str] = set()
    for feed in FEEDS:
        if feed_filter and feed.key != feed_filter:
            continue
        for i in range(0, len(wanted), 100):
            chunk = wanted[i:i + 100]
            try:
                data = client.table(feed.table).select("*").in_("url", chunk).execute().data or []
            except Exception as e:
                print(f"warn: could not read {feed.table}: {e}", file=sys.stderr)
                continue
            for r in data:
                u = r.get("url")
                if u and u not in seen:
                    seen.add(u)
                    rows.append(r)
    return rows


def _acc_line(label: str, scorecard: dict) -> str:
    bits = []
    for f in _LENS_FIELDS:
        a = scorecard["accuracy"].get(f, {})
        acc = a.get("accuracy")
        acc_s = "n/a" if acc is None else f"{acc * 100:.1f}%"
        bits.append(f"{f}={acc_s} (n={a.get('n', 0)})")
    return f"{label}: " + ", ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B the deployed lens prompt vs stored labels on the gold set.")
    ap.add_argument("--gold", default=DEFAULT_GOLD, help=f"gold JSONL (default: {DEFAULT_GOLD})")
    ap.add_argument("--feed", help="limit to one feed key")
    args = ap.parse_args()

    try:
        gold = load_gold(args.gold)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: could not load gold set: {e}", file=sys.stderr)
        return 1
    problems = validate(gold)
    if problems:
        print(f"warn: {len(problems)} gold problem(s) — run eval_run.py --validate-gold to list them.",
              file=sys.stderr)

    present = _read_gold_rows(gold, args.feed)
    if not present:
        print("No gold articles found in the feed tables — nothing to A/B "
              "(are the gold URLs from a pruned window?).", file=sys.stderr)
        return 1

    v1_preds = {r["url"]: r for r in present if r.get("maturity_stage")}
    print(f"gold labels: {len(gold)}   present in DB: {len(present)}   "
          f"carry a v1 label: {len(v1_preds)}")

    # v2 challenger — classify every present article with the deployed agent, in memory.
    from analytics.lens import LensClassifier
    v2_preds = LensClassifier().classify_in_memory(present)

    sc_v2_all = score_all(gold, v2_preds, _LENS_FIELDS)
    print(_acc_line(f"v2 absolute (all {len(present)} present)", sc_v2_all))

    if not v1_preds:
        print("\nNo gold article carries a stored v1 label — no v1 baseline to compare against. "
              "Showing v2 absolute accuracy only.")
        return 0

    # Head-to-head on the common set (the articles v1 actually classified).
    common_v2 = {u: v2_preds[u] for u in v1_preds if u in v2_preds}
    sc_v1 = score_all(gold, v1_preds, _LENS_FIELDS)
    sc_v2_common = score_all(gold, common_v2, _LENS_FIELDS)
    print()
    print(render_ab("v1 (stored)", sc_v1, "v2 (fresh)", sc_v2_common))
    print("\nKeep the winner: if v2 wins it's already deployed; if v1 wins, revert "
          "MOT_Lens_Agent.md + LENS_PROMPT_VERSION to v1 and re-paste.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
