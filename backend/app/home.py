"""
/api/home — the landing page's one cheap payload.

The home page is orientation, not analysis: the product promise backed by live
numbers, today's bottom line, and one teaser stat per surface. Everything here
comes from the data layer's TTL cache or a single cached read — deliberately
NOT the ~50-query briefing assembly (see the SRE finding on /api/briefing).
Every block degrades to None/zeros so a fresh deployment renders a clean page.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter

from . import data

router = APIRouter(prefix="/api/home", tags=["home"])


def pulse_counts(rows: list[dict], today: date) -> dict:
    """Pure: articles in the last 7 days + distinct feeds active in them."""
    cutoff = (today - timedelta(days=7)).isoformat()
    recent = [r for r in rows if str(r.get("published_at") or "")[:10] >= cutoff]
    return {
        "articles_7d": len(recent),
        "feeds_active": len({r.get("_feed_label") for r in recent} - {None}),
    }


def brief_teaser(row: dict | None) -> dict | None:
    """Pure: the home page's 'today' strip from a cached strategist row."""
    if not row or not row.get("strategic_read"):
        return None
    read = row["strategic_read"]
    signals = read.get("signals") or []
    return {
        "as_of": row.get("as_of"),
        "bottom_line": read.get("bottom_line") or "",
        "confidence": read.get("confidence"),
        "signal_count": len(signals),
        "top_signal": (signals[0].get("title") if signals else None),
    }


def _latest_brief() -> dict | None:
    """Most recent cached daily strategist row, TTL-cached like the other reads."""

    def load() -> dict | None:
        try:
            from analytics.strategist import Strategist

            recent = Strategist(data._supabase()).recent(focus="daily", limit=1)
            return recent[0] if recent else None
        except Exception:
            return None

    return data._cache.get_or_set("home:brief", ttl=300, producer=load)


def _tech_teaser() -> dict:
    """On-curve/watching counts plus the flagship examples (best-covered placed
    technologies) for the home page's workflow strip; pure compute over cache."""
    try:
        from analytics.tech_layer import apply_anchors, display_stage, placements

        placed = apply_anchors(placements(data.rows(30)))
        on_curve = [p for p in placed if p.get("stage_articles") and not p.get("watching")]
        watching = [p for p in placed if p.get("watching")]
        flagship = sorted(on_curve, key=lambda p: p.get("stage_articles") or 0, reverse=True)
        examples = [{
            "tech": p.get("tech"),
            "label": p.get("label"),
            "domain": p.get("domain"),
            "maturity": display_stage(p),
            "articles": p.get("stage_articles") or 0,
        } for p in flagship[:3] if p.get("tech")]
        return {"on_curve": len(on_curve), "watching": len(watching), "examples": examples}
    except Exception:
        return {"on_curve": 0, "watching": 0, "examples": []}


@router.get("")
def home() -> dict:
    import analytics.forecasts as fc

    preds = data.predictions()
    tr = fc.track_record(preds)
    basis = fc.records_by_basis(preds)

    # The worked example for the pitch: the radar's best current detection —
    # the concrete "we surfaced this before anyone tracked it" story. Prefers
    # candidates with a research signal (the fuller narrative); fail-open.
    radar_example = None
    try:
        from analytics.radar import list_candidates

        cands = [c for c in list_candidates(data._supabase())
                 if c.get("status") in ("new", "promoted")]
        if cands:
            best = max(cands, key=lambda c: (
                (c.get("evidence") or {}).get("papers") or 0,
                (c.get("evidence") or {}).get("mentions") or 0))
            ev = best.get("evidence") or {}
            radar_example = {
                "label": best.get("label"),
                "status": best.get("status"),
                "mentions": ev.get("mentions") or 0,
                "sources": ev.get("sources") or 0,
                "papers": ev.get("papers") or 0,
                "first_detected": best.get("first_detected"),
            }
    except Exception:
        pass

    return {
        "today": brief_teaser(_latest_brief()),
        "record": {
            "external": basis["external"],
            "resolved": tr["resolved"],
            "open": tr["open"],
            "total": tr["total"],
        },
        "tech": _tech_teaser(),
        "pulse": pulse_counts(data.rows(30), date.today()),
        "falsifier_events": len(data.falsifier_events() or []),
        "radar_example": radar_example,
    }
