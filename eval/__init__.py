"""
Lodestar evaluation harness — measures each pipeline stage against a hand-labelled
gold set so prompt/reducer changes can be proven, not asserted.

  gold.py     — gold-label schema, loader, validator (pure)
  scoring.py  — per-field accuracy + confusion, extraction completeness,
                rollup-integrity recompute-and-diff (pure)
  ../eval_run.py — the CLI that loads the gold set, fetches predictions
                   (fixture or live Supabase), and prints a scorecard.

The gold set itself (gold_labels.jsonl) is hand-labelled — see README.md.
"""
