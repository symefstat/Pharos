"""
Per-stage run-ledger — record one row per (stage, feed) per pipeline run into the
never-pruned `feed_runs` table (SQL Tables/feed_runs.sql).

Why: the pipeline used to log its data losses (parser drops; lens rows the agent
never returned) to stdout and throw the counts away. Persisting them gives the
eval harness a data-quality time series and gives the Phase-4 freshness monitor
something to alert on (a stalled feed, a no-op stage).

`build_record` is pure (unit-tested). `RunLedger.record` is the thin Supabase
write; it degrades to a logged no-op if the table isn't applied yet, so a pending
migration — or any ledger hiccup — can never be the thing that breaks a feed run.
"""

from __future__ import annotations

import logging
from typing import Optional

from supabase import Client

from db import get_supabase

logger = logging.getLogger(__name__)

LEDGER_TABLE = "feed_runs"


def build_record(stage: str, feed: Optional[str], metrics: Optional[dict],
                 ok: bool = True, error: Optional[str] = None) -> dict:
    """Pure. Assemble one `feed_runs` row. `feed`/`error` may be None; `metrics`
    is coerced to a plain dict. `run_at` is left to the DB default (NOW())."""
    return {
        "stage": str(stage),
        "feed": (str(feed) if feed is not None else None),
        "ok": bool(ok),
        "metrics": dict(metrics or {}),
        "error": (str(error) if error else None),
    }


def _is_missing_table_error(err: Exception) -> bool:
    """True if a write failed because `feed_runs` isn't created yet — i.e. the
    migration is pending. Matches only the specific missing-relation signatures
    (PostgREST PGRST205 schema-cache miss; Postgres 42P01 undefined_table) so a
    real write error isn't silently swallowed. Pure."""
    msg = str(err).lower()
    if LEDGER_TABLE not in msg:
        return False
    return any(tok in msg for tok in
               ("could not find", "does not exist", "schema cache", "pgrst205", "42p01"))


class RunLedger:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()

    def record(self, stage: str, feed: Optional[str], metrics: Optional[dict],
               ok: bool = True, error: Optional[str] = None) -> bool:
        """Insert one ledger row. Returns True if written, False if it degraded
        (table not applied, or any write error). Never raises — logging a run must
        not be able to break the run."""
        row = build_record(stage, feed, metrics, ok=ok, error=error)
        try:
            self.client.table(LEDGER_TABLE).insert(row).execute()
            return True
        except Exception as e:
            if _is_missing_table_error(e):
                logger.warning(
                    "feed_runs table not found — skipping run-ledger write. "
                    "Apply SQL Tables/feed_runs.sql to capture per-stage metrics."
                )
            else:
                logger.warning("Run-ledger write failed (stage=%s feed=%s): %s", stage, feed, e)
            return False
