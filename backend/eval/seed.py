"""
Gold-set seeding — turn already-classified feed articles into a ready-to-edit
labelling file, so the human corrects the lens's guesses instead of hunting for
URLs and labelling from a blank page (model-assisted labelling).

Both functions are pure; gold_seed.py supplies the Supabase read.

⚠️ The seed pre-fills each row with the LENS'S CURRENT GUESS. Those guesses are
exactly what the gold set exists to grade — so they must be *verified and
corrected* against the article, not rubber-stamped. Accepting them unchecked makes
the gold set echo the lens (gold == prediction → meaningless 100% accuracy, and a
biased A/B). Adjudicate each row against its title/summary.
"""

from __future__ import annotations

from typing import Callable, Sequence

# Underscore keys are labelling context only — load_gold/label_from_dict ignore
# unknown keys, so they can stay in the final gold_labels.jsonl harmlessly.
_TITLE_KEY = "_title"
_SUMMARY_KEY = "_summary"


def dedupe_by_url(items: Sequence, url_fn: Callable) -> list:
    """Drop later items that repeat an earlier item's url. An article cross-posted
    across feeds is stored in several feed tables (url is unique only *within* a
    table), so the candidate pool can carry the same url twice; the gold set must key
    on each url once. Preserves first-seen order. Pure."""
    seen: set = set()
    out: list = []
    for it in items:
        u = url_fn(it)
        if u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


def stratified_sample(items: Sequence, n: int, key_fn: Callable) -> list:
    """Round-robin draw up to `n` items, balanced across buckets keyed by `key_fn`,
    so no single bucket (e.g. the 'growth' stage, or the busiest feed) dominates the
    sample — the confusion matrix needs coverage of every stage and the boundaries.
    Deterministic (preserves input order within a bucket). Pure."""
    if n <= 0:
        return []
    buckets: dict = {}
    for it in items:
        buckets.setdefault(key_fn(it), []).append(it)
    queues = [list(b) for b in buckets.values()]
    out: list = []
    while len(out) < n:
        progressed = False
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop(0))
                progressed = True
        if not progressed:
            break  # every bucket drained
    return out


def build_seed_row(row: dict, feed_key: str, prefill: bool = True) -> dict:
    """Build one editable gold-seed line from a classified feed row. `_title`/
    `_summary` carry the article text so the human can adjudicate in place. Pure.

    prefill=True  (default): the four label fields are pre-filled with the lens's
        CURRENT guess — fast (correct only the wrong ones), but the guesses are what
        the gold set exists to grade, so they MUST be verified, not rubber-stamped.
    prefill=False: the label fields are left null (the human labels each from the
        article) and the lens's guess is moved to a `_guess` reference key. Slower
        but bias-free — the gold set can't accidentally echo the lens."""
    guess = {
        "maturity_stage": row.get("maturity_stage"),
        "adoption_stage": row.get("adoption_stage"),
        "business_impact": row.get("business_impact"),
        "scope": row.get("scope"),
    }
    seed = {
        "url": row.get("url"),
        "feed": feed_key,
        "maturity_stage": guess["maturity_stage"] if prefill else None,
        "adoption_stage": guess["adoption_stage"] if prefill else None,
        "business_impact": guess["business_impact"] if prefill else None,
        "scope": guess["scope"] if prefill else None,
        "notes": "",
        _TITLE_KEY: row.get("title"),
        _SUMMARY_KEY: row.get("summary"),
    }
    if not prefill:
        seed["_guess"] = guess  # reference only (underscore key → ignored by load_gold)
    return seed
