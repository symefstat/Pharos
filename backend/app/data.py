"""
Data layer for the API — the same Supabase reads the Streamlit app does, but with
no Streamlit dependency. The existing analytics modules (analytics.*, tickers,
finance) are pure and import cleanly, so this layer's only job is to (a) put the
project root on sys.path, (b) load .env, (c) fetch the three raw inputs the Capital
read needs (rows / financials / prices) and (d) cache them in-process with a TTL so
every API request doesn't re-hit Supabase.

The shapes returned here are exactly what the Streamlit `_framework_rows()`,
`_company_financials()` and `_stock_prices()` helpers produce — see Home.py.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

# ── expose backend packages and repo-root runtime files regardless of CWD ──────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for import_root in (PROJECT_ROOT, BACKEND_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

# Load the project's .env explicitly (config.py also calls load_dotenv(), but being
# explicit means the API works even when launched from a different CWD).
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass


# ── tiny in-process TTL cache (mirrors Streamlit's @st.cache_data(ttl=...)) ──────
class _TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, object]] = {}
        self._lock = Lock()

    def get_or_set(self, key: str, ttl: float, producer):
        now = time.monotonic()
        with self._lock:
            hit = self._store.get(key)
            if hit and (now - hit[0]) < ttl:
                return hit[1]
        value = producer()  # produced outside the lock — slow network call
        with self._lock:
            self._store[key] = (now, value)
        return value

    def set(self, key: str, value) -> None:
        """Store a freshly-produced value, resetting its TTL clock. Used by the
        background warmer so accessors keep serving without a cold miss."""
        with self._lock:
            self._store[key] = (time.monotonic(), value)

    def set_keep_good(self, key: str, value) -> None:
        """Warmer write with stale-serving (H2): an empty result must never
        replace good cached data — during a Supabase blip the loaders degrade
        to []/{} , and blindly `set()`ing that would actively blank every page
        while health still reads fine. Keeps (and re-stamps) the previous value
        so it survives the TTL until real data returns."""
        with self._lock:
            prev = self._store.get(key)
            if not value and prev and prev[1]:
                logger.warning("warm refresh of %r returned empty — keeping previous data", key)
                self._store[key] = (time.monotonic(), prev[1])
                return
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_cache = _TTLCache()


def _supabase():
    from db import get_supabase

    return get_supabase()


# ── raw inputs ──────────────────────────────────────────────────────────────────
def load_rows(days: int = 30) -> list[dict]:
    """Recent classified stories across all feeds (the Capital read's main input)."""
    from analytics.aggregator import PulseAggregator

    return PulseAggregator(_supabase()).all_recent(days=days)


def load_financials() -> list[dict]:
    """Fundamentals snapshots from financials_run.py (empty list if never run)."""
    try:
        return _supabase().table("company_financials").select("*").execute().data or []
    except Exception:
        # Degrade to empty for the reader, but never silently (H2): an outage
        # must be visible in the logs, not just render as "no data yet".
        logger.warning("load_financials failed — serving empty", exc_info=True)
        return []


def load_prices() -> dict:
    """{symbol: [{date, close}] ascending} — paginated past Supabase's 1000-row cap,
    exactly like Home.py `_stock_prices()`."""
    out: dict = {}
    try:
        sb = _supabase()
        start = 0
        while True:
            chunk = (
                sb.table("stock_prices")
                .select("symbol,day,close")
                .order("symbol")
                .order("day")
                .range(start, start + 999)
                .execute()
                .data
                or []
            )
            for r in chunk:
                out.setdefault(r["symbol"], []).append({"date": r["day"], "close": r["close"]})
            if len(chunk) < 1000:
                break
            start += 1000
    except Exception:
        logger.warning("load_prices failed — serving empty", exc_info=True)
        return {}
    return out


# ── cached accessors used by the routers ────────────────────────────────────────
def rows(days: int = 30) -> list[dict]:
    return _cache.get_or_set(f"rows:{days}", ttl=300, producer=lambda: load_rows(days))


def financials() -> list[dict]:
    return _cache.get_or_set("financials", ttl=900, producer=load_financials)


def prices() -> dict:
    return _cache.get_or_set("prices", ttl=900, producer=load_prices)


def load_predictions() -> list[dict]:
    """The forecast ledger, paginated past Supabase's 1000-row cap (Home.py
    `_predictions()`). Empty list if the table isn't set up."""
    out: list[dict] = []
    try:
        sb = _supabase()
        start = 0
        while True:
            chunk = (
                sb.table("predictions")
                .select("*")
                .order("made_on", desc=True)
                .range(start, start + 999)
                .execute()
                .data
                or []
            )
            out += chunk
            if len(chunk) < 1000:
                break
            start += 1000
    except Exception:
        logger.warning("load_predictions failed — serving empty", exc_info=True)
        return []
    return out


def predictions() -> list[dict]:
    return _cache.get_or_set("predictions", ttl=300, producer=load_predictions)


def load_falsifier_events(limit: int = 50) -> list[dict]:
    """Candidate falsifier evidence written by falsifier_run.py, newest first.
    Empty list (with the apply-the-SQL hint in the logs) if the table isn't
    set up — the UI simply shows no falsifier card."""
    from analytics.falsifier_watch import FalsifierWatch

    return FalsifierWatch(_supabase()).recent_events(limit=limit)


def falsifier_events() -> list[dict]:
    return _cache.get_or_set("falsifier_events", ttl=300, producer=load_falsifier_events)


def clear_cache() -> None:
    _cache.clear()


def warm_cache(heavy: bool = True) -> None:
    """Re-produce the cached datasets and store them under the standard keys the
    accessors read, resetting their TTLs. Called on startup and on a timer (see
    backend.app.main) so user requests hit warm data instead of paying for a cold
    Supabase read.

    `heavy=False` skips the paginated financials/prices reads (they have a longer
    TTL, so they don't need refreshing on every tick).

    Uses `set_keep_good`: during an outage the loaders return empty, and the
    warmer must serve stale-but-real data rather than overwrite it (H2)."""
    _cache.set_keep_good("rows:30", load_rows(30))
    _cache.set_keep_good("predictions", load_predictions())
    if heavy:
        _cache.set_keep_good("financials", load_financials())
        _cache.set_keep_good("prices", load_prices())
