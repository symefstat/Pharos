"""
/api/actions/* — the agent-triggering actions from the Streamlit UI:

  classify     → MOT Lens agent (analytics.lens.LensClassifier)
  strategist   → Strategist agent (analytics.strategist.Strategist.generate)
  refresh-all  → the full pipeline: feeds → MOT lens → rollup → strategist
                 → financials (yfinance) → forecasts

These are long-running (live agent / network calls), so each runs in a background
thread and reports progress through an in-process job registry the UI polls. Each
stage degrades independently — a failed stage is logged, not fatal — mirroring
Home.py's "Refresh all". Cache is cleared on completion so the next read is fresh.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from . import data
from .auth import require_admin
from .ratelimit import rate_limit

router = APIRouter(prefix="/api/actions", tags=["actions"])

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_MAX_JOBS = 50


def _new_job(kind: str) -> str:
    jid = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[jid] = {
            "id": jid,
            "kind": kind,
            "status": "running",
            "steps": [],
            "error": None,
            "started": time.time(),
            "finished": None,
        }
        # bound memory — drop the oldest finished jobs
        if len(_JOBS) > _MAX_JOBS:
            done = sorted(
                (j for j in _JOBS.values() if j["finished"]),
                key=lambda j: j["finished"] or 0,
            )
            for j in done[: len(_JOBS) - _MAX_JOBS]:
                _JOBS.pop(j["id"], None)
    return jid


def _log(jid: str, msg: str, ok: bool = True) -> None:
    with _LOCK:
        if jid in _JOBS:
            _JOBS[jid]["steps"].append({"msg": msg, "ok": ok})


def _finish(jid: str, error: str | None = None) -> None:
    with _LOCK:
        if jid in _JOBS:
            _JOBS[jid]["status"] = "error" if error else "done"
            _JOBS[jid]["error"] = error
            _JOBS[jid]["finished"] = time.time()


def get_job(jid: str) -> dict | None:
    with _LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else None


# ── runners (executed in a background thread) ────────────────────────────────────
def _run_classify(jid: str) -> None:
    try:
        from analytics.lens import LensClassifier

        _log(jid, "Classifying new articles via the MOT Lens agent…")
        res = LensClassifier().run(max_items_per_feed=16)
        _log(jid, f"Classified (per feed): {res}")
        data.clear_cache()
        _finish(jid)
    except Exception as e:
        _log(jid, f"Classification failed: {e}", ok=False)
        _finish(jid, str(e))


def _run_strategist(jid: str) -> None:
    try:
        from analytics.strategist import Strategist

        _log(jid, "Reasoning over the latest material developments…")
        Strategist(data._supabase()).generate()
        _log(jid, "Strategic read generated.")
        data.clear_cache()
        _finish(jid)
    except Exception as e:
        _log(jid, f"Strategist generation failed: {e}", ok=False)
        _finish(jid, str(e))


def _run_refresh_all(jid: str) -> None:
    """The full pipeline, in dependency order — each stage degrades independently."""
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from feeds import FEEDS
        from home_news_run import run_refresh

        sb = data._supabase()
        runnable = [f for f in FEEDS if getattr(f, "api_key", None)]
        _log(jid, f"Refreshing {len(runnable)} feeds in parallel…")
        parsed = upserted = 0
        if runnable:
            with ThreadPoolExecutor(max_workers=len(runnable)) as ex:
                futs = {ex.submit(run_refresh, f): f for f in runnable}
                for fut in as_completed(futs):
                    f = futs[fut]
                    try:
                        r = fut.result()
                        parsed += r.get("items_parsed", 0)
                        upserted += r.get("rows_upserted", 0)
                        _log(jid, f"✓ {f.label}: {r.get('items_parsed', 0)} parsed · {r.get('rows_upserted', 0)} upserted")
                    except Exception as e:
                        _log(jid, f"✗ {f.label}: {e}", ok=False)

        _log(jid, "Classifying new articles (MOT lens)…")
        try:
            from analytics.lens import LensClassifier

            lr = LensClassifier().run(max_items_per_feed=16)
            _log(jid, f"✓ MOT lens classified: {lr}")
        except Exception as e:
            _log(jid, f"✗ MOT lens skipped: {e}", ok=False)

        _log(jid, "Rebuilding analytics (rollup)…")
        try:
            from analytics.rollup import RollupBuilder

            RollupBuilder(sb).run()
            _log(jid, "✓ Rollup rebuilt")
        except Exception as e:
            _log(jid, f"✗ Rollup failed: {e}", ok=False)

        # Stage-history snapshot — the input the Stage-transitions section diffs.
        # Was previously only written by the scheduled pipeline (analytics_run.py),
        # so the button's "full pipeline" promise silently excluded transitions.
        _log(jid, "Snapshotting technology stages…")
        try:
            from analytics.tech_layer import TechAnalyst

            n = TechAnalyst(sb).snapshot()
            _log(jid, f"✓ Stage snapshot: {n} technologies")
        except Exception as e:
            _log(jid, f"✗ Stage snapshot skipped: {e}", ok=False)

        _log(jid, "Embedding new articles (news vector index)…")
        try:
            import news_embed

            er = news_embed.run(sb)
            _log(jid, f"✓ News embeddings: +{er.get('embedded', 0)} new · {er.get('total', '?')} total")
        except Exception as e:
            _log(jid, f"✗ News embedding skipped: {e}", ok=False)

        _log(jid, "Generating the strategist read…")
        try:
            from analytics.strategist import Strategist

            Strategist(sb).generate()
            _log(jid, "✓ Strategist read generated")
        except Exception as e:
            _log(jid, f"✗ Strategist skipped: {e} — retry it alone with the "
                      "'Regenerate strategist' button (no need to re-run the feeds)", ok=False)

        _log(jid, "Enriching financials (yfinance)…")
        try:
            import financials_run

            fr = financials_run.run(sb)
            _log(jid, f"✓ Financials: {fr.get('fundamentals', '?')}/{fr.get('tickers', '?')} fundamentals · {fr.get('prices', '?')} price series")
        except Exception as e:
            _log(jid, f"✗ Financials skipped: {e}", ok=False)

        _log(jid, "Generating & resolving forecasts…")
        try:
            import forecast_run

            as_of = datetime.now(timezone.utc).date().isoformat()
            added = forecast_run.generate(sb, as_of)
            resolved = forecast_run.resolve(sb, as_of)
            _log(jid, f"✓ Forecasts: +{added} new · {resolved} resolved")
        except Exception as e:
            _log(jid, f"✗ Forecasts skipped: {e}", ok=False)

        # Dossier narratives — the Dossier Analyst agent writes the cached
        # verdict per placed technology. Runs LAST so the packs carry today's
        # placements, transitions, and forecasts. Skips cleanly without the key.
        _log(jid, "Writing dossier narratives (Dossier Analyst agent)…")
        try:
            import os

            from analytics.dossier_agent import ENV_KEY as _DOSSIER_KEY
            from analytics.dossier_agent import generate_narratives

            if not os.getenv(_DOSSIER_KEY):
                _log(jid, f"— narratives skipped: {_DOSSIER_KEY} not set")
            else:
                from analytics.tech_layer import apply_anchors, placements as _placements

                from .mot import _assemble_dossier, _registry

                classified = [r for r in data.rows(days=30) if r.get("maturity_stage")]
                plc = apply_anchors(_placements(classified, _registry()))
                placed = [p["tech"] for p in plc if p.get("tech") and not p.get("watching")]
                dossiers = []
                for key in placed:
                    try:
                        dossiers.append(_assemble_dossier(key))
                    except Exception as e:
                        _log(jid, f"✗ dossier assembly {key}: {e}", ok=False)
                stats = generate_narratives(
                    sb, dossiers, log=lambda m, ok=True: _log(jid, m, ok=ok))
                _log(jid, f"✓ Narratives: {stats['generated']} written · {stats['failed']} failed")
        except Exception as e:
            _log(jid, f"✗ Dossier narratives skipped: {e}", ok=False)

        # Radar scan — surface candidate technologies from the stories that
        # matched NO tracked technology. Runs last (needs the fresh corpus);
        # fails open to the deterministic tag fallback without TOQAN_SCOUT.
        _log(jid, "Scanning the unmatched corpus (Radar / Scout agent)…")
        try:
            from technologies import registry as _registry_fn

            from analytics.radar import run_radar

            rr = run_radar(sb, data.rows(days=30), _registry_fn(sb),
                           log=lambda m, ok=True: _log(jid, m, ok=ok))
            _log(jid, f"✓ Radar: {rr['surfaced']} candidates surfaced "
                      f"from {rr['corpus']} unmatched stories")
        except Exception as e:
            _log(jid, f"✗ Radar skipped: {e}", ok=False)

        _log(jid, f"Done — {parsed} parsed · {upserted} upserted across {len(runnable)} feeds.")
        data.clear_cache()
        _finish(jid)
    except Exception as e:
        _log(jid, f"Refresh failed: {e}", ok=False)
        _finish(jid, str(e))


def _run_feed(jid: str, key: str) -> None:
    """Refresh a single feed (Home.py render_feed's per-tab Refresh)."""
    try:
        from feeds import FEEDS
        from home_news_run import run_refresh

        feed = next((f for f in FEEDS if f.key == key), None)
        if not feed:
            _log(jid, f"Unknown feed '{key}'", ok=False)
            _finish(jid, "unknown feed")
            return
        _log(jid, f"Refreshing {feed.label}…")
        r = run_refresh(feed)
        _log(jid, f"✓ {r.get('items_parsed', 0)} parsed · {r.get('rows_upserted', 0)} upserted")
        data.clear_cache()
        _finish(jid)
    except Exception as e:
        _log(jid, f"Refresh failed: {e}", ok=False)
        _finish(jid, str(e))


def _run_scorecard(jid: str, entity: str) -> None:
    """Focused Strategist read on one entity (MOT scorecard 'Analyst's read')."""
    try:
        from analytics.strategist import Strategist

        _log(jid, f"Asking the Strategist for a read on {entity}…")
        Strategist(data._supabase()).generate(focus=entity)
        _log(jid, f"Analyst's read on {entity} generated.")
        data.clear_cache()
        _finish(jid)
    except Exception as e:
        _log(jid, f"Read generation failed: {e}", ok=False)
        _finish(jid, str(e))


def _run_embed_news(jid: str) -> None:
    """Embed any not-yet-embedded articles into the news vector index."""
    try:
        import news_embed

        _log(jid, "Embedding new articles into the news vector index…")
        er = news_embed.run(data._supabase())
        _log(jid, f"✓ News embeddings: +{er.get('embedded', 0)} new · {er.get('total', '?')} total")
        data.clear_cache()
        _finish(jid)
    except Exception as e:
        _log(jid, f"News embedding failed: {e}", ok=False)
        _finish(jid, str(e))


def _run_radar(jid: str, brief: str | None = None) -> None:
    """Standalone Radar scan — re-scan the unmatched corpus without re-running
    the feeds. With a `brief`, the Scout answers the analyst's question over
    the same evidence (the directed-scan box on the Radar page)."""
    try:
        from technologies import registry as registry_fn

        from analytics.radar import run_radar

        _log(jid, f"Directed scan — asking the Scout: {brief}" if brief
                  else "Scanning the unmatched corpus (Radar / Scout agent)…")
        sb = data._supabase()
        rr = run_radar(sb, data.rows(days=30), registry_fn(sb), brief=brief,
                       log=lambda m, ok=True: _log(jid, m, ok=ok))
        _log(jid, f"✓ Radar: {rr['surfaced']} candidates surfaced "
                  f"from {rr['corpus']} unmatched stories")
        data.clear_cache()
        _finish(jid)
    except Exception as e:
        _log(jid, f"Radar scan failed: {e}", ok=False)
        _finish(jid, str(e))


_RUNNERS = {
    "classify": _run_classify,
    "strategist": _run_strategist,
    "refresh-all": _run_refresh_all,
    "embed-news": _run_embed_news,
    "radar": _run_radar,
}


def _launch(kind: str, fn, *args) -> dict:
    # One live job per kind: agent runs are expensive (LLM calls, 512MB web
    # instance), and a re-click while one runs should re-attach, not fan out.
    with _LOCK:
        running = next(
            (j for j in _JOBS.values() if j["kind"] == kind and j["status"] == "running"),
            None,
        )
    if running:
        return {"job_id": running["id"], "status": "running", "kind": kind}
    jid = _new_job(kind)
    threading.Thread(target=fn, args=(jid, *args), daemon=True).start()
    return {"job_id": jid, "status": "running", "kind": kind}


# Admin-gated, and rate-limited as defense in depth: a leaked token must not
# allow unbounded background-job spawning (H1).
_ACTION_DEPS = [Depends(require_admin), Depends(rate_limit("actions", limit=12, window=60))]


@router.post("/feed/{key}", dependencies=_ACTION_DEPS)
def refresh_feed(key: str) -> dict:
    return _launch(f"feed:{key}", _run_feed, key)


# Admin-only: each call spends LLM budget and upserts a row that is later
# re-served publicly — an open endpoint means anonymous cost burn + stored
# prompt injection (launch review 2026-07-08, finding 0.2).
@router.post("/scorecard/{entity}", dependencies=_ACTION_DEPS)
def scorecard_read(entity: str) -> dict:
    return _launch(f"scorecard:{entity}", _run_scorecard, entity)


@router.post("/{kind}", dependencies=_ACTION_DEPS)
def start_action(kind: str) -> dict:
    fn = _RUNNERS.get(kind)
    if not fn:
        raise HTTPException(status_code=404,
                            detail=f"unknown action '{kind}' — one of: {sorted(_RUNNERS)}")
    return _launch(kind, fn)


@router.get("/status/{jid}")
def action_status(jid: str) -> dict:
    return get_job(jid) or {"error": "unknown job", "status": "error"}
