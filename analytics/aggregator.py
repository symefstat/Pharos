"""
Read-side analytics across all feed tables — powers the Pulse page and the
Executive Brief's data pack.

Reads the live feed tables (their retention window). Long-range trend analysis
uses the never-pruned `feed_daily_metrics` rollup instead (see rollup.py).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from supabase import Client

from db import get_supabase
from feeds import FEEDS
from home_news.parser import canonicalize_url
from analytics.entities import normalize as normalize_entity
from analytics.weights import article_weight

logger = logging.getLogger(__name__)

_SENTIMENTS = ("positive", "negative", "neutral")
ROLLUP_TABLE = "feed_daily_metrics"


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _normalize_url(url: str) -> str:
    """Collapse http/https, www, host case, trailing slash, #fragment and
    tracking params (same rules as the writer's `canonicalize_url`) so the same
    story syndicated across feeds dedupes to one key. Meaningful query params
    are KEPT — `?v=A` and `?v=B` are distinct stories, not duplicates (dropping
    the whole query over-merged them). Empty string if unparseable.

    NOTE: historical `feed_daily_metrics` rollups were built with the old
    query-dropping normalization; the eval's rollup-integrity recompute reuses
    this function, so expected diffs can appear on old days until those days are
    rebuilt."""
    if not url:
        return ""
    try:
        p = urlparse(canonicalize_url(url.strip()))
        netloc = p.netloc[4:] if p.netloc.startswith("www.") else p.netloc
        if not netloc:
            return ""
        key = f"{netloc}{p.path.rstrip('/')}"
        return f"{key}?{p.query}" if p.query else key
    except Exception:
        return ""


class PulseAggregator:
    """Cross-feed reads for the overview page."""

    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()

    def _fetch_feed_rows(self, table: str, limit: int = 300) -> list[dict]:
        try:
            resp = (
                self.client.table(table)
                .select("*")
                .order("published_at", desc=True)
                .order("fetched_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.warning("Pulse: could not read %s: %s", table, e)
            return []

    def all_recent(self, days: int = 7) -> list[dict]:
        """Rows across all feeds within `days`, annotated with feed key/label/icon.

        Deduped by normalized URL — a story syndicated into several feeds is kept
        once (first feed wins) and annotated with `_also_in` listing the others,
        so Pulse/Entities don't triple-count it.
        """
        cutoff = date.today() - timedelta(days=days)
        out: list[dict] = []
        seen: dict[str, int] = {}  # normalized url -> index in `out`
        for feed in FEEDS:
            for row in self._fetch_feed_rows(feed.table):
                pub = _parse_date(row.get("published_at"))
                if pub is not None and pub < cutoff:
                    continue
                norm = _normalize_url(row.get("url") or "")
                if norm and norm in seen:
                    existing = out[seen[norm]]
                    if feed.label != existing.get("_feed_label"):
                        also = existing.setdefault("_also_in", [])
                        if feed.label not in also:
                            also.append(feed.label)
                    continue
                row = dict(row)
                row["_feed_key"] = feed.key
                row["_feed_label"] = feed.label
                row["_feed_icon"] = feed.icon
                if norm:
                    seen[norm] = len(out)
                out.append(row)
        return out

    # ── Targeted server-side queries (cheap retrieval for the Strategist) ──────
    def _fetch_feed_filtered(
        self,
        table: str,
        *,
        days: int,
        business_impact: Optional[str] = None,
        require_lens: bool = False,
        limit: int = 200,
    ) -> list[dict]:
        """Fetch recent rows from one feed with server-side filters applied.

        Pushes the date / materiality / classified predicates to PostgREST so the
        Strategist retrieves only what it needs instead of fetch-all-then-filter.
        Undated rows (published_at IS NULL) are excluded — the Strategist reasons
        over dated, recent developments.
        """
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        try:
            q = self.client.table(table).select("*").gte("published_at", cutoff)
            if business_impact:
                q = q.eq("business_impact", business_impact)
            if require_lens:
                q = q.not_.is_("maturity_stage", "null")
            resp = q.order("published_at", desc=True).limit(limit).execute()
            return resp.data or []
        except Exception as e:
            logger.warning("Pulse: filtered read of %s failed: %s", table, e)
            return []

    def targeted_recent(
        self,
        *,
        days: int = 14,
        business_impact: Optional[str] = "material",
        require_lens: bool = False,
        limit_per_feed: int = 60,
    ) -> list[dict]:
        """Cross-feed rows matching server-side filters, annotated + URL-deduped.

        Defaults to material stories in the last 14 days — the Strategist's focus
        set. Pass business_impact=None to drop the materiality filter, or
        require_lens=True to keep only MOT-classified rows.
        """
        out: list[dict] = []
        seen: dict[str, int] = {}
        for feed in FEEDS:
            rows = self._fetch_feed_filtered(
                feed.table,
                days=days,
                business_impact=business_impact,
                require_lens=require_lens,
                limit=limit_per_feed,
            )
            for row in rows:
                norm = _normalize_url(row.get("url") or "")
                if norm and norm in seen:
                    existing = out[seen[norm]]
                    if feed.label != existing.get("_feed_label"):
                        also = existing.setdefault("_also_in", [])
                        if feed.label not in also:
                            also.append(feed.label)
                    continue
                row = dict(row)
                row["_feed_key"] = feed.key
                row["_feed_label"] = feed.label
                row["_feed_icon"] = feed.icon
                if norm:
                    seen[norm] = len(out)
                out.append(row)
        return out

    def top_material_stories(self, rows: list[dict], limit: int = 12) -> list[dict]:
        """Material-impact stories first; backfill with contextual to fill the list."""
        material = [r for r in rows if (r.get("business_impact") or "").lower() == "material"]
        if len(material) < limit:
            material += [r for r in rows if (r.get("business_impact") or "").lower() == "contextual"]
        material.sort(
            key=lambda r: (str(r.get("published_at") or ""), str(r.get("fetched_at") or "")),
            reverse=True,
        )
        return material[:limit]

    def quick_stats(self, rows: list[dict]) -> dict:
        sentiment: Counter = Counter()
        companies: Counter = Counter()            # raw mention counts
        companies_w: Counter = Counter()          # significance/source-weighted
        countries: Counter = Counter()
        per_feed: Counter = Counter()
        material = 0
        for r in rows:
            s = (r.get("sentiment") or "").lower()
            if s in _SENTIMENTS:
                sentiment[s] += 1
            w = article_weight(r)
            for c in (r.get("companies") or []):
                n = normalize_entity(str(c))
                if n:
                    companies[n] += 1
                    companies_w[n] += w
            if r.get("country"):
                countries[str(r["country"])] += 1
            per_feed[r.get("_feed_label", "?")] += 1
            if (r.get("business_impact") or "").lower() == "material":
                material += 1
        return {
            "total": len(rows),
            "material": material,
            "sentiment": dict(sentiment),
            "top_companies": companies.most_common(8),
            # Weighted ranking (material + reputable-source coverage counts more) —
            # mirrors the Trends Share-of-Voice default so Pulse names the same leaders.
            "top_companies_weighted": [(n, round(v, 1)) for n, v in companies_w.most_common(8)],
            "top_countries": countries.most_common(8),
            "per_feed": dict(per_feed),
        }

    def snapshot(self, days: int = 7, top_n: int = 12) -> dict:
        rows = self.all_recent(days=days)
        return {
            "as_of": datetime.now(timezone.utc).date().isoformat(),
            "days": days,
            "stats": self.quick_stats(rows),
            "top_stories": [self._slim(r) for r in self.top_material_stories(rows, limit=top_n)],
        }

    def feeds_health(self) -> list[dict]:
        """Per-feed operational status: key present?, row count, % lens-classified,
        last fetched_at, last rollup date. A handful of cheap count/limit-1 reads
        per feed — cache it in the UI (it doesn't change between refreshes)."""
        out: list[dict] = []
        for feed in FEEDS:
            info = {
                "key": feed.key,
                "label": feed.label,
                "icon": feed.icon,
                "env_key": feed.env_key,
                "has_key": bool(feed.api_key),
                "rows": 0,
                "classified": None,  # None = unknown (e.g. lens columns not applied yet)
                "last_fetched": None,
                "last_rollup": None,
            }
            try:
                r = self.client.table(feed.table).select("id", count="exact").limit(1).execute()
                info["rows"] = r.count or 0
            except Exception as e:
                logger.warning("health: row count failed for %s: %s", feed.table, e)
            try:
                r = (
                    self.client.table(feed.table)
                    .select("id", count="exact")
                    .not_.is_("maturity_stage", "null")
                    .limit(1)
                    .execute()
                )
                info["classified"] = r.count or 0
            except Exception as e:
                # Most likely the MOT-lens columns aren't applied yet
                # (mot_lens_columns.sql); the UI shows "n/a". Debug, not warning,
                # so it isn't recurring noise.
                logger.debug("health: classified count unavailable for %s: %s", feed.table, e)
            try:
                r = (
                    self.client.table(feed.table)
                    .select("fetched_at")
                    .order("fetched_at", desc=True)
                    .limit(1)
                    .execute()
                )
                rows = r.data or []
                info["last_fetched"] = rows[0].get("fetched_at") if rows else None
            except Exception as e:
                logger.warning("health: last_fetched failed for %s: %s", feed.table, e)
            try:
                r = (
                    self.client.table(ROLLUP_TABLE)
                    .select("metric_date")
                    .eq("feed", feed.key)
                    .order("metric_date", desc=True)
                    .limit(1)
                    .execute()
                )
                rows = r.data or []
                info["last_rollup"] = rows[0].get("metric_date") if rows else None
            except Exception as e:
                logger.warning("health: last_rollup failed for %s: %s", feed.key, e)
            out.append(info)
        return out

    @staticmethod
    def _slim(r: dict) -> dict:
        return {
            "title": r.get("title"),
            "summary": r.get("summary"),
            "url": r.get("url"),
            "source_name": r.get("source_name"),
            "published_at": r.get("published_at"),
            "country": r.get("country"),
            "companies": r.get("companies") or [],
            "sentiment": r.get("sentiment"),
            "business_impact": r.get("business_impact"),
            "scope": r.get("scope"),
            "feed_label": r.get("_feed_label"),
            "feed_icon": r.get("_feed_icon"),
            "also_in": r.get("_also_in") or [],
        }
