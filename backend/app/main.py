"""
Lodestar API — a thin FastAPI layer over the existing Python analytics.

This is the backend for the new React frontend (the Streamlit replacement). It
imports the project's pure analytics modules unchanged and exposes their output as
JSON. Run it from the project root:

    ./venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000

The Capital tab is the first migrated surface; other tabs get their own routers
under backend/app/ following the same pattern.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import data
from .ratelimit import rate_limit
from .capital import router as capital_router
from .forecasts import router as forecasts_router
from .ledger import router as ledger_router
from .explore import router as explore_router
from .mot import router as mot_router
from .briefing import router as briefing_router
from .watchlist import router as watchlist_router
from .theses import router as theses_router
from .feeds_api import router as feeds_router
from .actions import router as actions_router
from .prosus import router as prosus_router
from .auth import router as auth_router
from .home import router as home_router
from .methodology import router as methodology_router
from .analyst import router as analyst_router
from .radar import router as radar_router

# Serving-path observability (H6): a real logging config so the data layer's
# degradation warnings actually reach the platform log stream, plus an optional
# Sentry hook — zero-cost when SENTRY_DSN is unset.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Silence routine HTTP chatter, matching Home.py.
for _noisy in ("httpx", "httpcore", "hpack", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

_log = logging.getLogger("lodestar")

if os.getenv("SENTRY_DSN"):
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.0)
        _log.info("Sentry error tracking enabled")
    except ImportError:
        _log.warning("SENTRY_DSN is set but sentry-sdk is not installed — "
                     "add `sentry-sdk` to requirements.txt to enable it")

# ── background cache warmer ───────────────────────────────────────────────────────
# The data layer caches Supabase reads in-process with a TTL. Left alone, the first
# request after each TTL lapse (or after the instance restarts) pays for a cold read.
# This thread keeps the cache hot so users almost always hit warm data. Disable with
# WARM_CACHE=0 (e.g. in tests or local dev without Supabase).
_WARM_INTERVAL = 240  # seconds; must stay under the 300s rows/predictions TTL
_warm_stop = threading.Event()


def _supabase_configured() -> bool:
    from config import Config

    try:
        Config.validate()
        return True
    except Exception:
        return False


def _warm_loop() -> None:
    tick = 0
    while not _warm_stop.is_set():
        if _supabase_configured():
            try:
                # Refresh the light datasets every tick; the longer-TTL financials/
                # prices reads only every 3rd tick (~12 min, under their 900s TTL).
                data.warm_cache(heavy=(tick % 3 == 0))
            except Exception:
                _log.warning("cache warm failed", exc_info=True)
            tick += 1
        _warm_stop.wait(_WARM_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    warmer: threading.Thread | None = None
    if os.getenv("WARM_CACHE", "1") != "0":
        _warm_stop.clear()
        warmer = threading.Thread(target=_warm_loop, name="cache-warm", daemon=True)
        warmer.start()
    try:
        yield
    finally:
        _warm_stop.set()
        if warmer is not None:
            warmer.join(timeout=2)


app = FastAPI(title="Lodestar API", version="0.1.0", lifespan=lifespan)

# The Vite dev server runs on :5173; allow it (and the common alternates) in dev.
# In prod the SPA is served from a different origin (e.g. a Render static site),
# so add that origin via CORS_ALLOW_ORIGINS (comma-separated) in the environment.
_allow_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
]
_extra_origins = os.getenv("CORS_ALLOW_ORIGINS", "")
_allow_origins += [o.strip() for o in _extra_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(capital_router)
app.include_router(forecasts_router)
app.include_router(ledger_router)
app.include_router(explore_router)
app.include_router(mot_router)
app.include_router(briefing_router)
app.include_router(watchlist_router)
app.include_router(theses_router)
app.include_router(feeds_router)
app.include_router(actions_router)
app.include_router(prosus_router)
app.include_router(auth_router)
app.include_router(home_router)
app.include_router(methodology_router)
app.include_router(analyst_router)
app.include_router(radar_router)


@app.get("/api/health")
def health() -> dict:
    """Liveness + a real reachability probe (H2).

    Always HTTP 200: the process is alive, and a Supabase outage isn't fixed by
    the platform restart-looping the container (which would also dump the warm
    cache). Outage visibility comes from `status: degraded` in the body — point
    the uptime monitor at the content, not just the status code."""
    from config import Config

    try:
        Config.validate()
        configured = True
    except Exception:
        configured = False

    reachable = False
    if configured:
        try:
            data._supabase().table("predictions").select("id").limit(1).execute()
            reachable = True
        except Exception:
            _log.warning("health: Supabase unreachable", exc_info=True)

    return {
        "status": "ok" if (configured and reachable) else "degraded",
        "supabase_configured": configured,
        "supabase_reachable": reachable,
    }


# Public (the UI's refresh buttons use it), but each call forces cold Supabase
# re-reads for every user — so per-IP capped (H1).
@app.post("/api/refresh", dependencies=[Depends(rate_limit("refresh", limit=6, window=60))])
def refresh() -> dict:
    """Drop the in-process cache so the next request re-reads Supabase."""
    data.clear_cache()
    return {"status": "ok", "cleared": True}
