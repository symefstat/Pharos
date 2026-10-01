"""
/api/explore/* — the 🔍 Explore tab: Trends, Entity dossiers, and the inputs the
Compare view needs. Mirrors Home.py render_trends() / render_entities() /
_compare_*(). Pure analytics (analytics.trends, analytics.entity_tracker,
analytics.tech_layer) → JSON; charts redrawn in React.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from . import data

router = APIRouter(prefix="/api/explore", tags=["explore"])

# Unbounded `days` drives an unbounded paginated Supabase scan (?days=100000);
# 365 comfortably covers every range the UI offers (H5).
_DAYS = Query(default=90, ge=1, le=365)


@router.get("/trends")
def trends(days: int = _DAYS, feed: str = "all", weighted: bool = True) -> dict:
    from analytics.trends import TrendsAggregator
    from feeds import FEEDS

    ta = TrendsAggregator(data._supabase())
    feed_keys = [f.key for f in FEEDS] if feed == "all" else [f.key for f in FEEDS if f.key == feed]
    rows = ta.rows(feed_keys or None, days)

    vol = ta.daily_volume(rows)
    sent = ta.daily_sentiment(rows)
    mom = ta.momentum(rows, days)
    # half_split keeps the SoV recent/prior halves equal-length and in lockstep
    # with momentum's split (the old local days//2 derivation was off by one).
    mid = ta.half_split(days)[1]
    sov = ta.voice_share(rows, mid, top=8, weighted=weighted)

    pos = sum(s["positive"] for s in sent)
    neg = sum(s["negative"] for s in sent)
    solid = [m for m in mom if not m.get("thin")]
    leader = max(solid, key=lambda m: m["pct"], default=None)
    if leader is not None:
        leader_kpi = {"feed": leader["feed"], "pct": leader["pct"], "thin": False}
    else:
        # Every feed is on a thin prior-half base — a % would be an artifact, so
        # surface the biggest absolute riser with raw counts instead.
        rising = [m for m in mom if m["recent"] > m["prior"]]
        lead = max(rising, key=lambda m: m["recent"] - m["prior"], default=None)
        leader_kpi = (
            {"feed": lead["feed"], "recent": lead["recent"], "prior": lead["prior"],
             "thin": True}
            if lead else None
        )
    # Aggregate volume trend with the same small-base guard headline() applies —
    # `thin` lets the UI caveat the volume KPI instead of implying a solid trend.
    volume_trend = ta.aggregate_momentum(mom)

    fields = ("by_company", "by_country", "by_impact", "by_scope", "by_tag")
    breakdowns = {
        f: [{"name": n, "count": c} for n, c in ta.sum_marginal(rows, f, top=12)] for f in fields
    }

    return {
        "feeds": [{"key": f.key, "label": f.label} for f in FEEDS],
        "feed": feed,
        "multi": feed == "all" and len(mom) > 1,
        "weighted": weighted,
        "empty": not rows,
        "headline": ta.headline(rows, days) if rows else "",
        "kpis": {
            "articles": sum(v["count"] for v in vol),
            "net": pos - neg,
            "pos": pos,
            "neg": neg,
            "leader": leader_kpi,
            "volume_trend": volume_trend,
        },
        "momentum": mom,
        "voice": sov,
        "volume": vol,
        "sentiment": sent,
        "breakdowns": breakdowns,
    }


@router.get("/entities")
def entities(days: int = _DAYS) -> dict:
    from analytics.entity_tracker import EntityTracker

    uni = EntityTracker(data._supabase()).universe(days=days, top=60)
    return {"universe": [{"name": n, "count": c} for n, c in uni]}


@router.get("/entity")
def entity(name: str, days: int = _DAYS) -> dict:
    from analytics.entity_tracker import EntityTracker, co_mentions, entity_read

    prof = EntityTracker(data._supabase()).profile(name, days=days)
    stories = prof.get("stories", []) or []
    return {
        "entity": name,
        "read": entity_read(name, prof),
        "weighted": prof.get("weighted", 0),
        "total": prof.get("total", 0),
        "feeds_count": prof.get("feeds_count", 0),
        "sentiment": prof.get("sentiment", {}),
        "by_feed": prof.get("by_feed", {}),
        "series": prof.get("series", []),
        "co_mentions": [{"name": n, "count": c} for n, c in co_mentions(stories, name)],
        "stories": stories,
    }


@router.get("/technologies")
def technologies() -> dict:
    """Tech placements for the Compare (technologies) view."""
    from analytics import mot_analyst as ma
    from analytics.tech_layer import display_stage, placements

    rows = [r for r in data.rows(days=30) if r.get("maturity_stage")]
    # Merged registry (static + self-serve tracked technologies) — degrades to
    # static inside registry() when the table is missing.
    from technologies import registry

    try:
        reg = registry(data._supabase())
    except Exception:
        reg = None
    plc = placements(rows, reg)
    out = [
        {
            "label": p["label"],
            "domain": p["domain"],
            "maturity": (display_stage(p) or "").replace("-", " "),
            "adoption": (display_stage(p, "adoption") or "").replace("-", " "),
            "articles": p.get("articles", 0),
            "entrants": p.get("entrants", 0),
            "move": (p.get("move") or "").replace("-", " "),
            "scurve": ma.scurve_position(p),
        }
        for p in plc
    ]
    return {"technologies": out}
