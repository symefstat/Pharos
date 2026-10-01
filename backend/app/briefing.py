"""
/api/briefing — the 🧭 Briefing: the accountable track record (calibration), the
Strategist read, the watchlist alerts, and the Pulse overview. Mirrors Home.py
render_briefing() = calibration banner + render_strategist + watchlist + render_pulse.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import data

router = APIRouter(prefix="/api/briefing", tags=["briefing"])


def _iso_key(value: object) -> str:
    """Sortable key for an ISO date/timestamp string. A date-only value is
    treated as end-of-day so 'resolved on the day you last visited' still counts
    as new (better to over-show than silently hide)."""
    s = str(value or "")
    return f"{s}T23:59:59" if len(s) == 10 else s


def match_signal_techs(signals: list[dict], techs: list) -> list[dict]:
    """Attach tracked-technology links to strategist signals (pure).

    Each signal's title + implication runs through the same registry keyword
    matcher the dossiers use; matches become {key, label} chips so a signal
    about foundry pricing links straight to /tech/advanced-logic. Capped at 2
    per signal — the chips are doors, not tags."""
    from analytics.tech_layer import match_technologies

    out = []
    for s in signals:
        row = {"title": s.get("title") or "", "summary": s.get("implication") or "",
               "companies": [], "tags": []}
        keys = list(match_technologies(row, techs))[:2]
        by_key = {t.key: t.label for t in techs}
        out.append({**s, "techs": [{"key": k, "label": by_key.get(k, k)} for k in keys]})
    return out


def count_since(preds: list[dict], transitions: list[dict], since_iso: str) -> dict:
    """Pure: how much accountable output landed after `since_iso` — resolved
    forecasts (resolved_on) and trustworthy stage transitions (as_of, suspect
    moves excluded). Backs the "since your last visit" strip."""
    since = str(since_iso).strip()
    resolved = sum(
        1 for p in preds
        if p.get("status") == "resolved" and p.get("resolved_on")
        and _iso_key(p["resolved_on"]) >= since
    )
    moved = sum(
        1 for t in transitions
        if not t.get("suspect") and t.get("as_of") and _iso_key(t["as_of"]) >= since
    )
    return {"resolved": resolved, "transitions": moved}


@router.get("")
def briefing() -> dict:
    import analytics.forecasts as fc

    sb = data._supabase()

    # ── calibration (the lead credibility hook) ──────────────────────────────
    preds = data.predictions()
    headline = fc.calibration_headline(preds)
    calibration = {"headline": headline, "tagline": fc.calibration_tagline(headline)}

    # ── strategist read ──────────────────────────────────────────────────────
    strategist = None
    try:
        from analytics.strategist import Strategist, portfolio_summary

        recent = Strategist(sb).recent(focus="daily", limit=1)
        row = recent[0] if recent else None
        if row and row.get("strategic_read"):
            read = row["strategic_read"]
            # Signal → dossier links: the one workflow connection the Briefing
            # was missing. Best-effort — a registry failure just means no chips.
            try:
                from technologies import registry

                read = {**read, "signals": match_signal_techs(
                    read.get("signals") or [], registry(sb))}
            except Exception:
                pass
            # Decision owner + persona, lifted from each signal's rationale at
            # serve time — stored reads gain the fields without regeneration.
            try:
                from analytics.strategist import extract_addressee, persona_of

                read = {**read, "signals": [
                    {**sig,
                     "owner": extract_addressee(str(sig.get("action_rationale") or "")),
                     "persona": persona_of(sig)}
                    for sig in (read.get("signals") or [])
                ]}
            except Exception:
                pass
            strategist = {
                "as_of": row.get("as_of"),
                "focus": row.get("focus"),
                "window_days": row.get("window_days"),
                "read": read,
                "portfolio": portfolio_summary(read),
                "stories": row.get("stories") or [],
            }
    except Exception:
        strategist = None

    # ── watchlist ─────────────────────────────────────────────────────────────
    try:
        from analytics.watchlist import Watchlist

        wl = Watchlist(sb)
        watchlist = {"items": wl.items(), "alerts": wl.alerts()}
    except Exception:
        watchlist = {"items": [], "alerts": []}

    # ── pulse overview ─────────────────────────────────────────────────────────
    from analytics.aggregator import PulseAggregator

    agg = PulseAggregator(sb)
    snap = agg.snapshot(days=7, top_n=12)
    try:
        health = agg.feeds_health()
    except Exception:
        health = []

    pulse = {
        "stats": snap.get("stats", {}),
        "top_stories": snap.get("top_stories", []),
        "health": health,
    }

    # ── new on the radar ───────────────────────────────────────────────────────
    # The horizon scan's freshest evidence-gated candidates — the daily entry
    # point should surface what the machine found before you knew to ask.
    radar: list[dict] = []
    try:
        from analytics.radar import list_candidates, trim_why

        for c in list_candidates(sb):
            if c.get("status") != "new":
                continue
            ev = c.get("evidence") or {}
            radar.append({
                "key": c.get("key"),
                "label": c.get("label"),
                "why": trim_why(str(c.get("why") or ""), 160),
                "mentions": ev.get("mentions") or 0,
                "sources": ev.get("sources") or 0,
                "papers": ev.get("papers") or 0,
                "research_stage": bool(ev.get("research_stage")),
                "first_detected": c.get("first_detected"),
            })
            if len(radar) >= 3:
                break
    except Exception:
        pass

    return {
        "calibration": calibration,
        "strategist": strategist,
        "watchlist": watchlist,
        "pulse": pulse,
        "radar": radar,
    }


@router.get("/since")
def briefing_since(ts: str) -> dict:
    """What landed since the visitor's last-visit timestamp (client-supplied ISO):
    resolved forecasts + trustworthy stage transitions. Cheap — the predictions
    read is the data-layer cache; transitions reuse the tech-history read."""
    ts = (ts or "").strip()
    if len(ts) < 10 or not ts[:4].isdigit():
        raise HTTPException(status_code=400, detail="ts must be an ISO timestamp")

    preds = data.predictions()
    try:
        from analytics.tech_layer import TechAnalyst

        transitions = TechAnalyst(data._supabase()).transitions()
    except Exception:
        transitions = []
    return count_since(preds, transitions, ts)
