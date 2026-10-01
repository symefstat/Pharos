"""
Trend analytics over the never-pruned `feed_daily_metrics` rollup.

Powers the Trends dashboard: volume/momentum, sentiment over time, top
companies/countries, and materiality/scope/tag mix — per feed or across all
feeds. Returns plain Python structures; the UI builds the charts.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta
from typing import Iterable, Optional

from supabase import Client

from db import get_supabase
from feeds import FEEDS_BY_KEY
from analytics.weights import weighted_companies_in_row, weighted_company_counts

logger = logging.getLogger(__name__)

ROLLUP_TABLE = "feed_daily_metrics"
_SENTIMENTS = ("positive", "negative", "neutral")
# Below this prior-half (base) article count, a momentum % is not trustworthy —
# a 2→265 swing would read +13150%. The % is zeroed and the row flagged `thin`
# so the UI can caveat/suppress it. This also covers the 0→1 all-new swing.
_MIN_MOMENTUM_BASE = 5
# Share guard, applied per feed AND to the aggregate: a prior half that is a
# sliver of the recent one (window started mid-ramp) makes any % an ingest
# artifact, even when the absolute floor is cleared — a 20→1015 feed would
# headline "+4975%". The % is only trusted when the prior half is at least
# this share of the recent half.
_MIN_PRIOR_SHARE = 0.25
# Aggregate (all-feeds) absolute floor for headline(): below this many prior-half
# articles the whole-window % is suppressed in favour of honest wording.
_MIN_AGG_PRIOR_BASE = 30


def _feed_label(key: str) -> str:
    feed = FEEDS_BY_KEY.get(key)
    return feed.label if feed else (key or "?")


class TrendsAggregator:
    """Reads the daily rollup and reduces it into chart-ready structures."""

    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()

    def rows(self, feed_keys: Optional[Iterable[str]], days: int) -> list[dict]:
        # `days - 1` because gte is inclusive of today: the window is exactly
        # `days` calendar days (today plus the days-1 before it), not days+1 —
        # otherwise the half-splits below compare uneven halves.
        cutoff = (date.today() - timedelta(days=max(0, days - 1))).isoformat()
        try:
            q = (
                self.client.table(ROLLUP_TABLE)
                .select("*")
                .gte("metric_date", cutoff)
                .order("metric_date")
            )
            keys = list(feed_keys) if feed_keys else None
            if keys:
                q = q.in_("feed", keys)
            return q.execute().data or []
        except Exception as e:
            logger.warning("Trends: could not read %s: %s", ROLLUP_TABLE, e)
            return []

    # ---- time series ----
    @staticmethod
    def daily_volume(rows: list[dict]) -> list[dict]:
        """[{date, feed, count}] — one record per (day, feed)."""
        return [
            {
                "date": str(r.get("metric_date")),
                "feed": _feed_label(r.get("feed", "")),
                "count": int(r.get("total_articles") or 0),
            }
            for r in rows
        ]

    @staticmethod
    def daily_sentiment(rows: list[dict]) -> list[dict]:
        """[{date, positive, negative, neutral, net}] summed across feeds per day."""
        by_day: dict[str, Counter] = {}
        for r in rows:
            c = by_day.setdefault(str(r.get("metric_date")), Counter())
            for k, v in (r.get("by_sentiment") or {}).items():
                if k in _SENTIMENTS:
                    c[k] += int(v or 0)
        out = []
        for d in sorted(by_day):
            c = by_day[d]
            out.append(
                {
                    "date": d,
                    "positive": c.get("positive", 0),
                    "negative": c.get("negative", 0),
                    "neutral": c.get("neutral", 0),
                    "net": c.get("positive", 0) - c.get("negative", 0),
                }
            )
        return out

    @staticmethod
    def sum_marginal(rows: list[dict], field: str, top: int = 10,
                     weighted: bool = False) -> list[tuple[str, int]]:
        """Sum a JSONB marginal (by_company/by_country/by_tag/...) across all rows.

        With `weighted=True` and `field == "by_company"`, returns significance/
        source-weighted company counts (folding `by_company_breakdown`); otherwise
        raw counts. `weighted` is ignored for non-company fields."""
        if weighted and field == "by_company":
            return weighted_company_counts(rows).most_common(top)
        c: Counter = Counter()
        for r in rows:
            for k, v in (r.get(field) or {}).items():
                c[k] += int(v or 0)
        return c.most_common(top)

    @staticmethod
    def half_split(days: int) -> tuple[str, str]:
        """Equal-length half-split of the `days`-day window ending today.

        Returns (lo, mid) ISO dates: the recent half is metric_date >= mid, the
        prior half is lo <= metric_date < mid. Both halves span exactly days//2
        calendar days (the leftover oldest day of an odd window falls before
        `lo`), so perfectly flat volume compares to exactly 0% momentum. Callers
        deriving a `mid` for voice_share should use this too, so the SoV split
        can't drift from momentum's."""
        h = max(1, days // 2)
        today = date.today()
        return ((today - timedelta(days=2 * h - 1)).isoformat(),
                (today - timedelta(days=h - 1)).isoformat())

    @staticmethod
    def momentum(rows: list[dict], days: int) -> list[dict]:
        """Per-feed volume in the recent half vs the prior half of the window.
        Halves are equal-length (see half_split); flat volume reads 0%."""
        lo, mid = TrendsAggregator.half_split(days)
        recent: Counter = Counter()
        prior: Counter = Counter()
        for r in rows:
            d = str(r.get("metric_date"))
            if d < lo:
                continue  # odd-window leftover day — dropped to keep halves equal
            label = _feed_label(r.get("feed", ""))
            n = int(r.get("total_articles") or 0)
            if d >= mid:
                recent[label] += n
            else:
                prior[label] += n
        out = []
        for f in sorted(set(recent) | set(prior)):
            rec, pri = recent.get(f, 0), prior.get(f, 0)
            # `thin` flags a base too small to yield a trustworthy % (a 2→265 swing
            # would read +13150%; a 0→1 swing +100%), or a prior half that is a
            # sliver of the recent one (mid-ramp window — same share guard as the
            # aggregate). The % is zeroed — never shown off a thin base — and the
            # UI additionally caveats/suppresses the row.
            thin = pri < _MIN_MOMENTUM_BASE or pri < _MIN_PRIOR_SHARE * rec
            pct = 0.0 if thin else (rec - pri) / pri * 100
            out.append({"feed": f, "recent": rec, "prior": pri, "pct": round(pct, 1),
                        "thin": thin})
        out.sort(key=lambda x: x["recent"], reverse=True)
        return out

    @staticmethod
    def voice_share(rows: list[dict], mid: str, field: str = "by_company",
                    top: int = 8, weighted: bool = False) -> dict:
        """Share of voice — each entity's share of `field` mentions in the recent half
        of the window (metric_date ≥ `mid`), with the point-change (pp) vs the prior
        half. The long tail is bucketed into 'Others'. `mid` (ISO date) is injected so
        this stays pure/testable; mirrors `momentum`'s recent-vs-prior split.

        With `weighted=True` (only meaningful for the default `by_company` field),
        each entity's contribution is folded through the significance/source weights
        (`by_company_breakdown`), so shares reflect material, reputable coverage
        rather than raw volume. Counts are then floats.

        Returns {slices: [{name, count, share, delta}], total} (recent-half total)."""
        recent: Counter = Counter()
        prior: Counter = Counter()
        use_weighted = weighted and field == "by_company"
        for r in rows:
            bucket = recent if str(r.get("metric_date")) >= mid else prior
            if use_weighted:
                for name, w in weighted_companies_in_row(r):
                    bucket[name] += w
            else:
                for k, v in (r.get(field) or {}).items():
                    bucket[k] += int(v or 0)
        total = sum(recent.values())
        if not total:
            return {"slices": [], "total": 0, "n_entities": 0}
        prev_total = sum(prior.values())

        def sh(c: Counter, n: str, tot: int) -> float:
            return round(100 * c.get(n, 0) / tot, 1) if tot else 0.0

        names = [n for n, _ in recent.most_common(top)]
        slices = []
        for n in names:
            s = sh(recent, n, total)
            ps = sh(prior, n, prev_total) if prev_total else None
            slices.append({"name": n, "count": recent[n], "share": s,
                           "delta": round(s - ps, 1) if ps is not None else None})
        shown = sum(recent[n] for n in names)
        if total - shown > 0:
            slices.append({"name": "Others", "count": total - shown,
                           "share": round(100 * (total - shown) / total, 1), "delta": None})
        # n_entities = distinct entities in the recent half (the long tail's true size).
        return {"slices": slices, "total": total, "n_entities": len(recent)}

    @staticmethod
    def aggregate_momentum(mom: list[dict]) -> dict:
        """Whole-window (all-feeds) volume momentum from `momentum()`'s per-feed
        output: {recent, prior, pct, thin}. `thin` marks a prior half too small
        for the aggregate % to be trustworthy — below _MIN_AGG_PRIOR_BASE articles
        or under _MIN_AGG_PRIOR_SHARE of the recent half (a window that started
        mid-ramp) — in which case pct is zeroed, mirroring the per-feed guard;
        headline() swaps the % claim for honest low-base wording and the UI can
        caveat the KPI. Pure."""
        rec = sum(m["recent"] for m in mom)
        pri = sum(m["prior"] for m in mom)
        thin = pri < _MIN_AGG_PRIOR_BASE or pri < _MIN_PRIOR_SHARE * rec
        pct = 0.0 if thin else (rec - pri) / pri * 100
        return {"recent": rec, "prior": pri, "pct": round(pct, 1), "thin": thin}

    @staticmethod
    def headline(rows: list[dict], days: int) -> str:
        """One-line analyst read of the window — overall momentum, the fastest
        riser and the sharpest faller, and net sentiment. Pure."""
        if not rows:
            return ""
        total = sum(int(r.get("total_articles") or 0) for r in rows)
        mom = TrendsAggregator.momentum(rows, days)
        sent = TrendsAggregator.daily_sentiment(rows)
        pos = sum(s["positive"] for s in sent)
        neg = sum(s["negative"] for s in sent)
        # Aggregate small-base guard: a thin prior half (absolute floor OR <25% of
        # the recent half) must not headline a "+12250% vs prior half" artifact —
        # state the raw counts honestly instead of a % off a base that isn't there.
        agg = TrendsAggregator.aggregate_momentum(mom)
        rec, pri = agg["recent"], agg["prior"]
        if agg["thin"]:
            base = (f"volume ramping from a low base — **{rec}** recent-half articles "
                    f"vs **{pri}** prior (% vs prior suppressed)"
                    if rec >= pri else
                    f"prior-half base too small for a reliable trend — **{rec}** "
                    f"recent-half articles vs **{pri}** prior")
            parts = [f"**{total}** articles in range — {base}."]
        else:
            parts = [f"**{total}** articles in range — {'up' if agg['pct'] >= 0 else 'down'} "
                     f"**{agg['pct']:+.0f}%** vs the prior half."]
        # Only call out movers with a real prior baseline (avoid the no-history +100%)
        # AND enough volume to trust the %, matching the thin-feed gate the KPI/chart use
        # — otherwise a near-dead feed (prior 1 → recent 3) headlines as "+200%".
        movers = [m for m in mom if m["prior"] > 0 and not m.get("thin")]
        risers = sorted((m for m in movers if m["pct"] > 0), key=lambda m: -m["pct"])
        fallers = sorted((m for m in movers if m["pct"] < 0), key=lambda m: m["pct"])
        if risers:
            parts.append(f"Accelerating: **{risers[0]['feed']}** ({risers[0]['pct']:+.0f}%).")
        if fallers:
            parts.append(f"Cooling: **{fallers[0]['feed']}** ({fallers[0]['pct']:+.0f}%).")
        parts.append(f"Net sentiment **{pos - neg:+d}** ({pos} pos / {neg} neg).")
        return " ".join(parts)
