#!/usr/bin/env python3
"""
Seed a gold-labelling file from already-classified feed articles.

Pulls a sample of classified articles, balanced across feeds and maturity stages,
and writes an editable JSONL pre-filled with each article's real URL, title,
summary, and the lens's current guess. You then VERIFY + correct each row against
its title/summary and save it as backend/eval/gold_labels.jsonl — far faster than hunting
for URLs and labelling from scratch.

⚠️ The pre-filled labels are the lens's guesses — the very thing the gold set
exists to grade. Correct them honestly; do NOT rubber-stamp (that makes the gold
set echo the lens and the A/B meaningless).

⚠️ Makes a live Supabase read (no writes). Run only when you mean to.

  ./venv/bin/python backend/gold_seed.py [--n 200] [--feed KEY] [--out backend/eval/gold_labels.seed.jsonl]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from eval.seed import build_seed_row, dedupe_by_url, stratified_sample

DEFAULT_OUT = str(Path(__file__).resolve().parent / "eval" / "gold_labels.seed.jsonl")
_COLS = "url,title,summary,maturity_stage,adoption_stage,business_impact,scope"


def _read_classified(feed_filter: str | None, per_feed_limit: int) -> list[tuple[str, dict]]:
    """Read classified rows (maturity_stage NOT NULL) from each feed table.
    Returns a flat list of (feed_key, row)."""
    from db import get_supabase
    from feeds import FEEDS

    client = get_supabase()
    out: list[tuple[str, dict]] = []
    for feed in FEEDS:
        if feed_filter and feed.key != feed_filter:
            continue
        try:
            rows = (
                client.table(feed.table).select(_COLS)
                .not_.is_("maturity_stage", "null")
                .order("published_at", desc=True).limit(per_feed_limit)
                .execute().data or []
            )
        except Exception as e:
            print(f"warn: could not read {feed.table}: {e}", file=sys.stderr)
            continue
        for r in rows:
            if r.get("url") and r.get("maturity_stage"):
                out.append((feed.key, r))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed a gold-labelling file from classified feed articles.")
    ap.add_argument("--n", type=int, default=200, help="target number of articles to seed (default 200)")
    ap.add_argument("--feed", help="limit to one feed key")
    ap.add_argument("--per-feed-limit", type=int, default=500, help="rows to read per feed before sampling")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"output JSONL (default: {DEFAULT_OUT})")
    ap.add_argument("--no-prefill", dest="prefill", action="store_false",
                    help="leave label fields blank (lens guess goes to a _guess reference key) — "
                         "bias-free labelling, can't echo the lens")
    ap.add_argument("--force", action="store_true", help="overwrite --out if it already exists")
    args = ap.parse_args()

    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        print(f"error: {out_path} already exists — pass --force to overwrite "
              "(this protects hand-labelled work, e.g. backend/eval/gold_labels.jsonl).", file=sys.stderr)
        return 1

    classified = _read_classified(args.feed, args.per_feed_limit)
    if not classified:
        print("No classified articles found — run the lens first, or check the feed filter.",
              file=sys.stderr)
        return 1

    # An article cross-posted across feeds is stored in several tables — keep it once.
    classified = dedupe_by_url(classified, url_fn=lambda fr: fr[1].get("url"))

    # Balance across (feed, maturity stage) so every stage/boundary gets coverage.
    sample = stratified_sample(classified, args.n, key_fn=lambda fr: (fr[0], fr[1].get("maturity_stage")))
    rows = [build_seed_row(row, feed_key, prefill=args.prefill) for feed_key, row in sample]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    print(f"Wrote {len(rows)} seed rows to {out_path} (from {len(classified)} classified articles).")
    print("\nNext:")
    if args.prefill:
        print(f"  1. Edit {out_path}: read each _title/_summary and CORRECT the four label fields")
        print("     (maturity_stage, adoption_stage, business_impact, scope) — they are the lens's")
        print("     UNVERIFIED guesses. Do not rubber-stamp; that makes the A/B meaningless.")
    else:
        print(f"  1. Edit {out_path}: read each _title/_summary and LABEL the four fields")
        print("     (maturity_stage, adoption_stage, business_impact, scope). The lens's guess is")
        print("     in `_guess` for reference only.")
    print("     Set a field to null if the article doesn't carry that signal.")
    print("  2. Save it as backend/eval/gold_labels.jsonl, then validate:")
    print("       ./venv/bin/python backend/eval_run.py --validate-gold")
    print("  3. Tell me, and I'll run the v1-vs-v2 A/B.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
