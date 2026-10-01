"""
/api/mot — the 🔭 MOT Analyst read, the full render_framework() surface:
S-curve + adoption (diffusion) lifecycle maps, stage transitions, diffusion bell,
strategic-move matrix, convergence radar, co-mention network, design-ferment,
measured performance/adoption benchmark curves, per-entity scorecards, and a
browse-by-lens corpus slice. Chart geometry (centroid → x) is computed here.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from . import data
from .auth import require_admin
from .ratelimit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mot", tags=["mot"])


def _registry() -> list:
    """The merged technology registry (static + self-serve DB rows), degrading
    to the static registry when Supabase is unavailable."""
    from technologies import TECHNOLOGIES, registry

    try:
        return registry(data._supabase())
    except Exception:
        return list(TECHNOLOGIES)


def _standards(days: int = 90) -> list[dict]:
    """Standards-battle timelines harvested from the Strategist brief history
    (one Supabase read; degrades to [] — the card simply shows its empty state)."""
    try:
        from analytics.standards import standards_timeline

        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        briefs = (
            data._supabase()
            .table("strategist_briefs")
            .select("as_of,strategic_read")
            .gte("as_of", cutoff)
            .order("as_of", desc=True)
            .limit(400)
            .execute()
            .data
            or []
        )
        return standards_timeline(briefs)
    except Exception as e:
        logger.warning("standards timeline unavailable (%s) — serving empty", e)
        return []


def _benchset(specs: dict, tech_by_key: dict) -> list[dict]:
    out = []
    for key, spec in specs.items():
        if key not in tech_by_key:
            continue
        out.append({
            "key": key,
            "label": tech_by_key[key].label,
            "metric": spec.get("metric"),
            "unit": spec.get("unit"),
            "lower_is_better": bool(spec.get("lower_is_better")),
            "note": spec.get("note", ""),
            "series": [{"date": d, "value": v} for d, v in spec.get("series", [])],
        })
    return out


@router.get("/scorecard-read")
def scorecard_read(entity: str) -> dict:
    """The focused Strategist read for one entity (MOT scorecard 'Analyst's read'),
    if one has been generated."""
    try:
        from analytics.strategist import Strategist

        rec = Strategist(data._supabase()).latest(focus=entity)
        if not rec or not rec.get("strategic_read"):
            return {"read": None}
        return {
            "entity": entity,
            "as_of": rec.get("as_of"),
            "read": rec["strategic_read"],
        }
    except Exception:
        return {"read": None}


def _stage_segments(snaps: list[dict], field: str) -> list[dict]:
    """Run-length-encode a technology's snapshot history on `field` (pure).

    `snaps` is oldest-first. Consecutive snapshots holding the same stage
    collapse into one segment `{stage, from, to, snapshots}`; unclassified
    days (NULL stage — below the evidence floor, or no coverage) extend
    nothing, so a coverage gap shows as a gap, not as a stage claim. A
    stage that flips a→b→a yields three segments — the flip is real history."""
    segs: list[dict] = []
    for s in snaps:
        stage = s.get(field)
        if not stage:
            continue
        as_of = str(s.get("as_of") or "")
        if segs and segs[-1]["stage"] == stage:
            segs[-1]["to"] = as_of
            segs[-1]["snapshots"] += 1
        else:
            segs.append({"stage": stage, "from": as_of, "to": as_of, "snapshots": 1})
    return segs


@router.get("/history")
def stage_history(days: int = 365) -> dict:
    """Long-run lifecycle record per technology — the never-pruned daily
    snapshots (technology_stage_history), run-length-encoded into stage
    segments. This is the 'keep tracking maturity beyond the 30-day window'
    surface: the S-curve places from a rolling news window (change detector);
    this endpoint serves where every technology has SAT, day by day.

    Stages are as displayed at snapshot time — the curated anchor floor is
    baked in, so a first post-anchor snapshot can show a step the news alone
    did not produce (the payload says so via `note`)."""
    from analytics.mot_analyst import ADOPTION_ORDER, MATURITY_ORDER
    from analytics.tech_layer import HISTORY_TABLE

    days = max(30, min(days, 3650))
    today = datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=days)).isoformat()

    # Page through the window (14 techs × 365d ≈ 5k rows — above the REST
    # per-request cap, so read in pages rather than one capped select).
    rows: list[dict] = []
    page = 1000
    try:
        sb = data._supabase()
        for start in range(0, 40 * page, page):
            batch = (
                sb.table(HISTORY_TABLE)
                .select("technology,as_of,label,domain,maturity_stage,adoption_stage,article_count")
                .gte("as_of", cutoff)
                # Deterministic page boundaries: order matches the PK so a
                # row never straddles (or vanishes between) two pages.
                .order("as_of", desc=False)
                .order("technology", desc=False)
                .range(start, start + page - 1)
                .execute()
                .data
                or []
            )
            rows.extend(batch)
            if len(batch) < page:
                break
    except Exception as e:
        logger.warning("stage history unavailable (%s) — serving empty", e)
        rows = []

    from technologies import domain_label

    by_tech: dict[str, list[dict]] = {}
    for r in rows:
        by_tech.setdefault(r.get("technology"), []).append(r)

    techs = []
    for key, snaps in by_tech.items():
        if not key:
            continue
        latest = snaps[-1]
        techs.append({
            "tech": key,
            "label": latest.get("label") or key,
            "domain": domain_label(latest.get("domain")),
            "maturity": _stage_segments(snaps, "maturity_stage"),
            "adoption": _stage_segments(snaps, "adoption_stage"),
            "first_seen": str(snaps[0].get("as_of") or ""),
            "last_seen": str(latest.get("as_of") or ""),
            "snapshots": len(snaps),
        })
    techs.sort(key=lambda t: ((t["domain"] or ""), t["label"].lower()))

    return {
        "days": days,
        "from": cutoff,
        "to": today.isoformat(),
        "maturity_order": list(MATURITY_ORDER),
        "adoption_order": list(ADOPTION_ORDER),
        "technologies": techs,
        "note": (
            "Stages are as displayed on each day (curated anchor floor included); "
            "gaps are days below the evidence floor or without classified coverage."
        ),
    }


def _tech_points(plc: list[dict], MO: list[str], AO: list[str], regimed: dict) -> list[dict]:
    """Chart-ready technology points from (anchored) placements — pure.

    World-truth additions (eval/reports/40_world_truth.md §4): `thin_signal`
    (< 10 stage-classified articles → hollow dot), `anchored`/`news_*` (the
    curated floor and the preserved news-derived stage), and `lifecycle_fit`
    (taxonomy misfits are kept in the payload but taken OFF both curves — the
    UI footnotes them under the placement table instead of plotting a dot).

    Evidence floor (domain-strategy plan): `watching` (< EVIDENCE_FLOOR
    stage-classified articles) takes a tech OFF both curves like a misfit,
    but it keeps its placement-table ROW — rendered with a
    "watching — insufficient evidence" badge instead of a stage position.
    """
    from analytics.tech_layer import display_stage

    def norm(cen, order):
        return round(cen / (len(order) - 1), 4) if cen is not None else None

    techs = []
    for p in plc:
        cen = p.get("stage_centroid")
        if cen is None and p.get("maturity") in MO:
            cen = float(MO.index(p["maturity"]))
        acen = p.get("adoption_centroid")
        cov = p.get("stage_articles")
        cov = p.get("articles", 0) if cov is None else cov
        acov = p.get("adoption_articles") or 0
        fit = p.get("lifecycle_fit", True) is not False
        watching = bool(p.get("watching"))
        techs.append({
            # Registry key — stable identity, used by the dossier export control.
            "tech": p.get("tech"),
            "label": p["label"],
            "domain": p["domain"],
            "maturity": (display_stage(p) or "").replace("-", " "),
            "adoption": (display_stage(p, "adoption") or "").replace("-", " "),
            "move": (p.get("move") or "").replace("-", " "),
            "articles": p.get("articles", 0),
            "entrants": p.get("entrants", 0),
            "coverage": cov,
            "x": norm(cen, MO),
            "mixed": bool(p.get("mixed")),
            "on_curve": cen is not None and cov >= 3 and fit and not watching,
            # adoption (diffusion) placement
            "ax": norm(acen, AO),
            "adoption_coverage": acov,
            "adoption_mixed": bool(p.get("adoption_mixed")),
            "on_adoption_curve": acen is not None and acov >= 3 and fit and not watching,
            "regime": regimed.get(p["label"]),
            # world-truth overlay (coverage floor + curated anchors + taxonomy fit)
            "thin_signal": bool(p.get("thin_signal")),
            # evidence floor: below EVIDENCE_FLOOR stage articles the tech is
            # off both curves ("watching") but keeps its placement-table row.
            "watching": watching,
            "anchored": bool(p.get("anchored")),
            "maturity_anchored": bool(p.get("maturity_anchored")),
            "adoption_anchored": bool(p.get("adoption_anchored")),
            "news_maturity": (p.get("news_maturity") or "").replace("-", " ") or None,
            "news_adoption": (p.get("news_adoption") or "").replace("-", " ") or None,
            "anchor_as_of": p.get("anchor_as_of"),
            "lifecycle_fit": fit,
            "lifecycle_note": p.get("lifecycle_note"),
            # Self-serve tracked technology (tracked_technologies row, not the
            # static registry) — the UI shows the archive affordance on these.
            "is_custom": bool(p.get("is_custom")),
        })
    return techs


@router.get("")
def mot(scope: str = "all") -> dict:
    from analytics import mot_analyst as ma
    from analytics.entity_tracker import (
        co_occurrence_matrix,
        domain_convergence,
        interpret_convergence,
    )
    from analytics.tech_layer import EVIDENCE_FLOOR, TechAnalyst, apply_anchors, placements
    from feeds import FEEDS

    # Scope at the source: filter rows to the selected feed once, so every
    # corpus-derived panel below (S-curve, counts, convergence, co-mention,
    # scorecards, browse, …) inherits the filter — not just diffusion/moves.
    rows_all = data.rows(days=30)
    rows = rows_all if scope == "all" else [r for r in rows_all if r.get("_feed_label") == scope]
    classified = [r for r in rows if r.get("maturity_stage")]

    MO, AO = ma.MATURITY_ORDER, ma.ADOPTION_ORDER
    # Anchored placements: curated world-truth floor + last-30-days news signal
    # (news can advance a stage past its anchor, never lower it below). The
    # MERGED registry (static + self-serve tracked_technologies rows) drives
    # the roll-up, so admin-added technologies match articles too.
    from technologies import TECH_BY_KEY as STATIC_BY_KEY
    from technologies import known_domains

    reg = _registry()
    custom_keys = {t.key for t in reg if t.key not in STATIC_BY_KEY}
    plc = apply_anchors(placements(classified, reg))
    # A freshly-added custom tech with zero matched coverage still gets its
    # placement-table row ("watching — insufficient evidence") — otherwise it
    # would be invisible (and unarchivable) until its first article lands.
    present = {p.get("tech") for p in plc}
    for t in reg:
        if t.key not in custom_keys or t.key in present:
            continue
        if scope != "all" and t.domain != scope:
            continue
        plc.append({
            "tech": t.key, "label": t.label, "domain": t.domain,
            "articles": 0, "entrants": 0,
            "maturity": None, "adoption": None, "move": None,
            "stage_articles": 0, "adoption_articles": 0,
            "stage_centroid": None, "adoption_centroid": None,
            "mixed": False, "adoption_mixed": False,
            "thin_signal": True, "watching": True,
        })
    for p in plc:
        p["is_custom"] = p.get("tech") in custom_keys
    scoped_labels = {p["label"] for p in plc}
    regimed = {r["label"]: r.get("regime") for r in ma.ferment_regime(plc)}
    techs = _tech_points(plc, MO, AO, regimed)

    diffusion = ma.diffusion_points(classified)
    moves = ma.move_matrix(classified)
    try:
        trans = TechAnalyst(data._supabase()).transitions()
    except Exception:
        trans = []
    # Transitions come from the global stage-history table; when a feed is
    # selected, keep only those for technologies present in the scoped view.
    if scope != "all":
        trans = [t for t in trans if t.get("label") in scoped_labels]
    # Evidence-floor discipline: a transition IS a stage claim, so a technology
    # currently below the floor ("watching") makes none here either — same rule
    # the curves, KPI count, and dossiers already follow. Its history remains
    # in the stage-history table and reappears once coverage clears the floor.
    placed_labels = {p["label"] for p in plc if not p.get("watching")}
    trans = [t for t in trans if t.get("label") in placed_labels]

    # convergence radar — sector domains only (cross-cutting lenses excluded as poles)
    cross_cutting = {f.label for f in FEEDS if getattr(f, "cross_cutting", False)}
    seams = domain_convergence(rows, exclude_feeds=cross_cutting)
    comatrix = co_occurrence_matrix(rows, top=14)

    # scorecards (templated 7-question readout per named entity)
    universe = ma.entity_universe(classified, top=40)
    scorecards = [ma.scorecard(classified, e) for e in universe]

    # measured benchmark curves (illustrative seed data)
    try:
        from benchmarks import ADOPTION_BENCHMARKS, BENCHMARKS
        from technologies import TECH_BY_KEY

        performance_curves = _benchset(BENCHMARKS, TECH_BY_KEY)
        adoption_curves = _benchset(ADOPTION_BENCHMARKS, TECH_BY_KEY)
    except Exception:
        performance_curves, adoption_curves = [], []
    # Reference curves are keyed by technology — scope them to the selected feed too.
    if scope != "all":
        performance_curves = [c for c in performance_curves if c["label"] in scoped_labels]
        adoption_curves = [c for c in adoption_curves if c["label"] in scoped_labels]

    # measured world curves — real, sourced series (analytics/measured_curves.py);
    # static data, deliberately NOT scoped: these are world benchmarks, not
    # corpus-derived, and each carries its own citation.
    from analytics.measured_curves import measured_curves

    # browse-by-lens corpus slice (most-recent classified, slimmed)
    browse = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "summary": r.get("summary"),
            "sentiment": r.get("sentiment"),
            "published_at": r.get("published_at"),
            "image_url": r.get("image_url"),
            "_feed_label": r.get("_feed_label"),
            "business_impact": r.get("business_impact"),
            "maturity_stage": r.get("maturity_stage"),
            "adoption_stage": r.get("adoption_stage"),
            "strategic_move": r.get("strategic_move"),
            "lens_rationale": r.get("lens_rationale"),
        }
        for r in sorted(classified, key=lambda r: r.get("published_at") or "", reverse=True)[:400]
    ]

    return {
        "feeds": [{"key": f.key, "label": f.label} for f in FEEDS],
        "scope": scope,
        "classified": len(classified),
        "total": len(rows),
        # Honest estimator (world-truth fix §4.2): the read line states what the
        # placements ARE — a curated anchor floor advanced by the news window —
        # before the agent narration, so the page never implies the 30-day news
        # centroid alone is a world-state claim.
        "scurve_interpret": (
            "Placements are anchored to curated stage assessments (Jul 2026); the "
            "last-30-days news signal can advance a technology past its anchor but "
            "never lower it below. "
            # Same floor as on_curve (EVIDENCE_FLOOR) so the narrative never
            # names a watching technology that isn't on the chart.
            + ma.interpret_tech(plc, min_articles=EVIDENCE_FLOOR)
        ),
        # NOTE: no separate "adoption_interpret" — the analytics produce exactly one
        # diffusion read (interpret_diffusion); it ships once as `diffusion_interpret`
        # below and is rendered on the diffusion card. A byte-identical copy under a
        # second name was dead payload (eval/reports/10_app_parity.md §2.1).
        "technologies": techs,
        # Evidence floor for curve placement — the UI badge quotes it, so the
        # number is never hardcoded client-side.
        "evidence_floor": EVIDENCE_FLOOR,
        "maturity_order": list(MO),
        "adoption_order": list(AO),
        "diffusion": diffusion,
        "diffusion_interpret": ma.interpret_diffusion(diffusion),
        "moves": moves,
        "move_order": list(ma.MOVE_ORDER),
        "move_interpret": ma.interpret_move(moves),
        "transitions": trans,
        # Standards battles — van-de-Kaa-style factor reads over time per
        # contested standard, harvested from the Strategist brief history.
        "standards": _standards(),
        # The valid domain labels for the self-serve tracking form.
        "tech_domains": known_domains(),
        "convergence": seams,
        "convergence_interpret": interpret_convergence(seams),
        "comatrix": comatrix,
        "scorecards": scorecards,
        "performance_curves": performance_curves,
        "adoption_curves": adoption_curves,
        "measured_curves": measured_curves(),
        "browse": browse,
    }


def _assemble_dossier(tech: str) -> dict:
    """Shared dossier assembly for the export download and the JSON page:
    anchored placement, stage-transition history, forecasts with falsifiers,
    resolved receipts, recent coverage, capital moves, and the measured curve.
    Raises 404 for a key outside the (merged) registry."""
    from analytics.dossier import build_dossier
    from analytics.measured_curves import measured_curves
    from analytics.tech_layer import TechAnalyst, apply_anchors, placements

    reg = _registry()
    if tech not in {t.key for t in reg}:
        raise HTTPException(status_code=404, detail=f"Unknown technology '{tech}'")

    rows = data.rows(days=30)
    classified = [r for r in rows if r.get("maturity_stage")]
    try:
        trans = TechAnalyst(data._supabase()).transitions()
    except Exception:
        trans = []                    # degrade: dossier ships without history

    from analytics.funding import tech_funding

    try:
        funding = tech_funding(data._supabase(), tech)
    except Exception:
        funding = None                # degrade: dossier ships without the panel

    d = build_dossier(
        tech,
        placements=apply_anchors(placements(classified, reg)),
        transitions=trans,
        predictions=data.predictions(),
        stories=rows,
        measured=measured_curves(),
        as_of=datetime.now(timezone.utc).date().isoformat(),
        techs=reg,
        funding=funding,
    )
    if d is None:                     # unreachable after the registry check; belt & braces
        raise HTTPException(status_code=404, detail=f"Unknown technology '{tech}'")

    # Agent-written narrative (Dossier Analyst, cached per refresh) — shown in
    # place of the deterministic read when one exists; None degrades to it.
    try:
        from analytics.dossier_agent import latest_narrative

        n = latest_narrative(data._supabase(), tech)
        d["agent_read"] = ({"text": n["narrative"], "as_of": str(n["as_of"])}
                           if n else None)
    except Exception:
        d["agent_read"] = None

    # Origin story: a technology promoted from Radar keeps its detection
    # provenance — when it surfaced, on what evidence, and the graded call
    # that promotion locked. Fail-open: no radar row (built-in tech, or the
    # table missing) simply means no panel.
    d["radar_origin"] = None
    try:
        from analytics.radar import CANDIDATES_TABLE

        rc = (data._supabase().table(CANDIDATES_TABLE)
              .select("label,why,first_detected,evidence,status")
              .eq("key", tech).eq("status", "promoted")
              .limit(1).execute().data or [])
        if rc:
            ev = rc[0].get("evidence") or {}
            d["radar_origin"] = {
                "first_detected": rc[0].get("first_detected"),
                "why": rc[0].get("why"),
                "mentions": ev.get("mentions") or 0,
                "sources": ev.get("sources") or 0,
                "papers": ev.get("papers") or 0,
                "research_stage": bool(ev.get("research_stage")),
                "found_via": ev.get("found_via"),
                "ledger_pred_id": ev.get("ledger_pred_id"),
            }
    except Exception:
        pass
    return d


# Rate-limited (real assembly work per call: placements + transitions + ledger
# reads + a render); public read like the rest of /api/mot.
@router.get("/dossier", dependencies=[Depends(rate_limit("mot_dossier", 10))])
def dossier(tech: str, fmt: str = "md") -> Response:
    """Exportable one-pager for one tracked technology (the analyst dossier),
    served as a download attachment in `md` or `pdf`. The JSON page view of the
    same assembly lives at /api/mot/tech/{key}."""
    if fmt not in ("md", "pdf"):
        raise HTTPException(status_code=400, detail="fmt must be 'md' or 'pdf'")
    from analytics.dossier import dossier_to_markdown, dossier_to_pdf

    d = _assemble_dossier(tech)
    filename = f"lodestar-dossier-{tech}-{d['as_of']}.{fmt}"
    if fmt == "pdf":
        return Response(
            content=dossier_to_pdf(d),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(
        content=dossier_to_markdown(d),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tech/{tech}", dependencies=[Depends(rate_limit("mot_dossier", 10))])
def tech_dossier(tech: str) -> dict:
    """The Technology Dossier page payload — the same assembly the export uses,
    as JSON: signal → lifecycle stage → forecasts → graded outcomes on one URL."""
    return _assemble_dossier(tech)


# ── self-serve technology tracking (tracked_technologies) ─────────────────────
# "Adding a technology is one entry" — an admin-UI entry instead of a code
# edit. Writes follow the theses.py pattern: admin-gated, rate-limited,
# validated. No GET — the merged registry already ships via the placements.

_TECH_RATE = rate_limit("mot_tech", limit=30, window=60)

_TRACKED_MIGRATION_HINT = (
    "technology tracking is not set up — apply "
    "'SQL Tables/tracked_technologies.sql' to enable it"
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_key(label: str) -> str:
    """Registry key (slug) from a display label: 'Edge AI chips' → 'edge-ai-chips'."""
    return _SLUG_RE.sub("-", (label or "").strip().lower()).strip("-")


def _raise_tracked(e: Exception) -> None:
    msg = str(e).lower()
    if "tracked_technologies" in msg and (
        "does not exist" in msg or "could not find" in msg or "pgrst205" in msg
    ):
        raise HTTPException(status_code=503, detail=_TRACKED_MIGRATION_HINT)
    raise HTTPException(status_code=502, detail=str(e))


class TrackTechnologyBody(BaseModel):
    label: str
    domain: str
    keywords: list[str]


@router.post("/technologies", dependencies=[Depends(_TECH_RATE)])
def track_technology(body: TrackTechnologyBody, _admin: str = Depends(require_admin)) -> dict:
    """Track a new technology: one validated row in tracked_technologies. The
    key is slugified from the label; it starts matching articles on the next
    read and shows as 'watching — insufficient evidence' until coverage accrues."""
    from technologies import TECH_BY_KEY, TRACKED_TABLE, known_domains

    label = (body.label or "").strip()
    if not 2 <= len(label) <= 60:
        raise HTTPException(status_code=400, detail="label must be 2-60 characters")
    domains = known_domains()
    domain = (body.domain or "").strip()
    if domain not in domains:
        raise HTTPException(
            status_code=400, detail=f"domain must be one of: {', '.join(domains)}"
        )
    # Keywords are lowercased substrings matched against title+summary+tags+
    # companies (technologies.py) — normalise the same way here.
    keywords = list(dict.fromkeys(
        k.strip().lower() for k in (body.keywords or []) if k and k.strip()
    ))
    if not 1 <= len(keywords) <= 10:
        raise HTTPException(status_code=400, detail="provide 1-10 non-empty keywords")
    if any(len(k) > 60 for k in keywords):
        raise HTTPException(status_code=400, detail="keywords must be at most 60 characters each")

    key = slugify_key(label)
    if not key:
        raise HTTPException(status_code=400, detail="label must contain letters or digits")
    if key in TECH_BY_KEY:
        raise HTTPException(
            status_code=409, detail=f"'{key}' is already a built-in tracked technology"
        )
    try:
        sb = data._supabase()
        existing = (
            sb.table(TRACKED_TABLE).select("key,archived").eq("key", key).execute().data or []
        )
        if existing and not existing[0].get("archived"):
            raise HTTPException(status_code=409, detail=f"'{key}' is already tracked")
        # Upsert so re-adding a previously archived key revives it (its old
        # stage history resumes) with the fresh label/domain/keywords.
        sb.table(TRACKED_TABLE).upsert(
            {"key": key, "label": label, "domain": domain,
             "keywords": keywords, "archived": False},
            on_conflict="key",
        ).execute()
    except HTTPException:
        raise
    except Exception as e:
        _raise_tracked(e)
    return {"ok": True, "technology": {
        "key": key, "label": label, "domain": domain, "keywords": keywords,
    }}


@router.delete("/technologies/{key}", dependencies=[Depends(_TECH_RATE)])
def untrack_technology(key: str, _admin: str = Depends(require_admin)) -> dict:
    """Soft archive: the technology drops out of the merged registry, but any
    stage history it accumulated is kept (and revives if the key is re-added)."""
    from technologies import TECH_BY_KEY, TRACKED_TABLE

    if key in TECH_BY_KEY:
        raise HTTPException(
            status_code=400, detail="built-in technologies cannot be archived"
        )
    try:
        hit = (
            data._supabase()
            .table(TRACKED_TABLE)
            .update({"archived": True})
            .eq("key", key)
            .eq("archived", False)
            .execute()
            .data
            or []
        )
    except Exception as e:
        _raise_tracked(e)
    if not hit:
        raise HTTPException(status_code=404, detail=f"tracked technology '{key}' not found")
    return {"ok": True, "archived": key}
