"""
Build the never-pruned per-feed daily metrics rollup (`feed_daily_metrics`).

Feed tables prune at 14–30 days, so any long-range trend (momentum vs last
month, sentiment over a quarter) needs history captured before pruning. This
recomputes the recent days each run and upserts on (feed, metric_date), so
running it on a schedule accumulates an unbounded history.

Cross-feed de-duplication: a story syndicated into several feeds (same URL) is
counted only under the FIRST feed it appears in (FEEDS order), mirroring
`PulseAggregator.all_recent`. Without this the cross-feed reads (Share of Voice,
top companies, entity tracker) triple-count a syndicated story. Consequence:
`total_articles` is "unique stories first-seen in this feed", so a feed that
mostly carries syndicated copies shows a lower count than its raw table size.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from supabase import Client

from db import get_supabase
from feeds import FEEDS, Feed
from analytics.aggregator import _normalize_url
from analytics.entities import normalize as normalize_entity
from analytics.weights import normalize_impact, source_tier

logger = logging.getLogger(__name__)

ROLLUP_TABLE = "feed_daily_metrics"


def _count_scalar(items: list[dict], field: str, lower: bool = True) -> dict:
    c: Counter = Counter()
    for r in items:
        v = r.get(field)
        if v:
            c[str(v).lower() if lower else str(v)] += 1
    return dict(c)


def _count_list(items: list[dict], field: str) -> dict:
    c: Counter = Counter()
    for r in items:
        for v in (r.get(field) or []):
            if v:
                c[str(v).strip().lower()] += 1
    return dict(c)


def _count_companies(items: list[dict]) -> dict:
    c: Counter = Counter()
    for r in items:
        for v in (r.get("companies") or []):
            n = normalize_entity(str(v))
            if n:
                c[n] += 1
    return dict(c)


def _count_company_breakdown(items: list[dict]) -> dict:
    """Per-company mention counts split by "<impact>|<tier>" bucket, so the ranked
    views can weight by significance (business_impact) and source authority
    (source_name → tier) at read time (see analytics/weights.py). Pure.
      e.g. { "Nvidia": { "material|t1": 2, "contextual|unknown": 1 } }"""
    out: dict[str, Counter] = {}
    for r in items:
        key = f"{normalize_impact(r.get('business_impact'))}|{source_tier(r.get('source_name'))}"
        for v in (r.get("companies") or []):
            n = normalize_entity(str(v))
            if n:
                out.setdefault(n, Counter())[key] += 1
    return {company: dict(buckets) for company, buckets in out.items()}


def dedup_by_feed(feed_rows: list[tuple[str, list[dict]]]) -> dict[str, list[dict]]:
    """Cross-feed URL de-dup, first-feed-wins by input order. `feed_rows` is an
    ordered list of (feed_key, rows). A story syndicated into several feeds is kept
    only under the first feed it appears in (mirrors `PulseAggregator.all_recent`'s
    `seen` dict). URL-less rows can't be de-duped, so they're always kept. Pure —
    so the rollup build and the eval integrity recompute share one implementation.

    Returns {feed_key: surviving_rows}."""
    survivors: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for feed_key, rows in feed_rows:
        kept: list[dict] = []
        for row in rows:
            norm = _normalize_url(row.get("url") or "")
            if norm and norm in seen:
                continue
            if norm:
                seen.add(norm)
            kept.append(row)
        survivors[feed_key] = kept
    return survivors


def build_rows(feed_key: str, rows: list[dict], now: str) -> list[dict]:
    """Bucket `rows` by published day and produce the (feed, metric_date) upsert
    dicts for `feed_daily_metrics`. `rows` should already be cross-feed-deduped
    (see `dedup_by_feed`). `now` (ISO timestamp) is injected for deterministic
    tests. Pure — the eval recompute mirrors this exact counting."""
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        d = str(r.get("published_at") or "")[:10]
        if len(d) == 10:
            by_day.setdefault(d, []).append(r)
    return [
        {
            "feed": feed_key,
            "metric_date": d,
            "total_articles": len(items),
            "by_tag": _count_list(items, "tags"),
            "by_company": _count_companies(items),
            "by_company_breakdown": _count_company_breakdown(items),
            "by_country": _count_scalar(items, "country", lower=False),
            "by_sentiment": _count_scalar(items, "sentiment"),
            "by_impact": _count_scalar(items, "business_impact"),
            "by_scope": _count_scalar(items, "scope"),
            "updated_at": now,
        }
        for d, items in by_day.items()
    ]


class RollupBuilder:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()

    def _rows(self, table: str, limit: int = 1000) -> list[dict]:
        try:
            resp = (
                self.client.table(table)
                .select("*")
                .order("published_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.warning("Rollup: could not read %s: %s", table, e)
            return []

    def run(self) -> dict:
        """Read every feed once, cross-feed de-dup, then upsert per-feed day-rows.

        De-dup spans feeds, so all reads happen up front before any feed is built;
        per-feed upserts stay independent (one feed failing doesn't sink the rest)."""
        now = datetime.now(timezone.utc).isoformat()
        feed_rows = [(feed.key, self._rows(feed.table)) for feed in FEEDS]
        survivors = dedup_by_feed(feed_rows)

        out: dict[str, int] = {}
        for feed in FEEDS:
            try:
                ups = build_rows(feed.key, survivors.get(feed.key, []), now)
                if ups:
                    self.client.table(ROLLUP_TABLE).upsert(
                        ups, on_conflict="feed,metric_date"
                    ).execute()
                out[feed.key] = len(ups)
                logger.info("Rollup: %s -> %d day-rows", feed.key, len(ups))
            except Exception as e:
                logger.warning("Rollup failed for %s: %s", feed.key, e)
                out[feed.key] = 0
        return out
