#!/usr/bin/env python3
"""
One-off: clean the forecast ledger of resolution artifacts.

Early runs resolved auto forecasts within days of making them — before they could
test the future (a same-day "confirm the present" bug, since fixed in
`forecast_run` / `analytics.forecasts`). Those premature resolutions are not real
track record and inflate the public scorecard. This removes them so the record
rebuilds honestly from forecasts that actually had a chance to play out.

Usage:
  python forecast_reset.py                # dry-run: report artifacts, delete nothing
  python forecast_reset.py --apply        # delete the prematurely-resolved AUTO rows
  python forecast_reset.py --all --apply  # delete ALL predictions (full clean slate)

Dry-run by default. Open and manually-graded (Strategist) forecasts are preserved
unless --all is given. Safe to re-run.

Deletions are TOMBSTONED, never silent: every deleted row is snapshotted into
`prediction_tombstones` (with a reason) before it goes. The preferred path is
the `ledger_maintenance_delete` RPC (SQL Tables/predictions_tombstones.sql),
which bundles tombstone + `SET LOCAL app.ledger_maintenance = 'on'` + delete in
one transaction — supabase-py cannot issue a SET LOCAL that survives across
PostgREST requests, so the trigger's escape hatch (see
SQL Tables/predictions_immutability.sql) is only reachable through that RPC or
the Supabase SQL editor. If the RPC isn't installed yet, this script degrades:
it still tombstones first, then plain-deletes; if even the tombstone table is
missing, or the immutability trigger blocks the plain delete, it aborts with
instructions instead of deleting anything.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from config import Config
from db import get_supabase
from analytics.forecasts import MIN_RESOLVE_DAYS

logger = logging.getLogger("forecast_reset")
_CHUNK = 500

TOMBSTONES_TABLE = "prediction_tombstones"
MAINTENANCE_RPC = "ledger_maintenance_delete"
REASON_PREMATURE = "premature-resolution cleanup"
REASON_ALL = "--all reset"


class LedgerMaintenanceError(RuntimeError):
    """A deletion could not proceed safely (no tombstone path / trigger block)."""


def _days_between(made, resolved) -> int | None:
    try:
        a = datetime.strptime(str(made)[:10], "%Y-%m-%d").date()
        b = datetime.strptime(str(resolved)[:10], "%Y-%m-%d").date()
        return (b - a).days
    except (TypeError, ValueError):
        return None


def is_premature_resolution(row: dict, min_days: int = MIN_RESOLVE_DAYS) -> bool:
    """A resolved AUTO forecast that resolved < `min_days` after it was made — i.e.
    it never tested the future (the same-day-resolution artifact). Pure; manual
    (Strategist) resolutions and still-open forecasts are never flagged."""
    if row.get("status") != "resolved" or row.get("kind") == "manual":
        return False
    d = _days_between(row.get("made_on"), row.get("resolved_on"))
    return d is not None and d < min_days


def build_tombstones(rows: list[dict], reason: str) -> list[dict]:
    """Full-row snapshots → append-only tombstone records. Pure: every deleted
    prediction leaves its complete original row (JSONB) plus the reason it was
    removed, so a deletion is never silent."""
    return [{"original": dict(r), "reason": reason} for r in rows]


def _is_missing_rpc_error(err: Exception) -> bool:
    """True if calling the maintenance RPC failed because the function hasn't
    been created yet (SQL Tables/predictions_tombstones.sql not applied) —
    PostgREST PGRST202 ('Could not find the function … in the schema cache')
    or Postgres 42883 ('function … does not exist'). Mirrors
    db.is_missing_column_error. Pure."""
    msg = str(err).lower()
    if MAINTENANCE_RPC not in msg:
        return False
    return any(tok in msg for tok in
               ("could not find", "does not exist", "schema cache", "pgrst202", "42883"))


def _is_missing_table_error(err: Exception, table: str) -> bool:
    """True if a read/write failed because `table` hasn't been created yet —
    Postgres 42P01 or PostgREST PGRST205 (cf. analytics.falsifier_watch). Pure."""
    msg = str(err).lower()
    if table not in msg:
        return False
    return any(tok in msg for tok in
               ("does not exist", "could not find", "schema cache", "pgrst205", "42p01"))


def _all_predictions(sb) -> list[dict]:
    out: list[dict] = []
    start = 0
    while True:
        chunk = (sb.table("predictions").select("*")
                 .order("made_on", desc=True).range(start, start + 999).execute().data or [])
        out += chunk
        if len(chunk) < 1000:
            break
        start += 1000
    return out


def _delete_rows_fallback(sb, rows: list[dict], reason: str) -> int:
    """Degraded path when the maintenance RPC isn't installed: tombstone FIRST
    (direct inserts), then a plain delete. Aborts — deleting nothing — if the
    tombstone table is missing or the immutability trigger blocks the delete."""
    tombs = build_tombstones(rows, reason)
    try:
        for i in range(0, len(tombs), _CHUNK):
            sb.table(TOMBSTONES_TABLE).insert(tombs[i:i + _CHUNK]).execute()
    except Exception as e:
        if _is_missing_table_error(e, TOMBSTONES_TABLE):
            raise LedgerMaintenanceError(
                f"the {TOMBSTONES_TABLE} table does not exist, so this deletion cannot "
                "be tombstoned. Apply 'SQL Tables/predictions_tombstones.sql' in the "
                "Supabase SQL editor (it also installs the ledger_maintenance_delete "
                "RPC), or run the reset there manually inside one transaction with "
                "SET LOCAL app.ledger_maintenance = 'on' — see "
                "SQL Tables/README_DURABILITY.md. Nothing was deleted.") from e
        raise
    ids = [r["id"] for r in rows if r.get("id") is not None]
    n = 0
    try:
        for i in range(0, len(ids), _CHUNK):
            batch = ids[i:i + _CHUNK]
            sb.table("predictions").delete().in_("id", batch).execute()
            n += len(batch)
    except Exception as e:
        if "immutable" in str(e).lower() or "ledger_maintenance" in str(e).lower():
            raise LedgerMaintenanceError(
                "the immutability trigger blocked the plain delete (resolved ledger "
                f"rows are protected; {n} already deleted in earlier chunks). Apply "
                "'SQL Tables/predictions_tombstones.sql' so the ledger_maintenance_delete "
                "RPC exists, or run the reset in the Supabase SQL editor with "
                "SET LOCAL app.ledger_maintenance = 'on' — see "
                "SQL Tables/README_DURABILITY.md. Tombstones for this batch were "
                "already written.") from e
        raise
    return n


def _delete_rows(sb, rows: list[dict], reason: str) -> int:
    """Delete via the ledger_maintenance_delete RPC — tombstones + the
    maintenance GUC (SET LOCAL) + the delete in ONE transaction, chunked.
    Falls back to tombstone-then-plain-delete when the RPC isn't installed."""
    ids = [r["id"] for r in rows if r.get("id") is not None]
    n = 0
    for i in range(0, len(ids), _CHUNK):
        batch = ids[i:i + _CHUNK]
        try:
            sb.rpc(MAINTENANCE_RPC, {"p_ids": batch, "p_reason": reason}).execute()
        except Exception as e:
            if _is_missing_rpc_error(e):
                logger.warning("%s RPC not installed — apply 'SQL Tables/"
                               "predictions_tombstones.sql'. Falling back to "
                               "tombstone-then-delete.", MAINTENANCE_RPC)
                remaining = [r for r in rows if r.get("id") in set(ids[i:])]
                return n + _delete_rows_fallback(sb, remaining, reason)
            raise
        n += len(batch)
    return n


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description="Clean forecast-ledger resolution artifacts.")
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry-run)")
    ap.add_argument("--all", action="store_true",
                    help="delete ALL predictions, not just the prematurely-resolved auto rows")
    args = ap.parse_args()

    load_dotenv()
    try:
        Config.validate()
    except ValueError as e:
        logger.error("%s — set them in .env before running.", e)
        return 1

    sb = get_supabase()
    rows = _all_predictions(sb)
    if args.all:
        targets, label = rows, "ALL predictions (full reset)"
    else:
        targets = [r for r in rows if is_premature_resolution(r)]
        label = f"auto forecasts resolved < {MIN_RESOLVE_DAYS}d after being made"

    print(f"Ledger: {len(rows)} predictions total.")
    print(f"Targeted for deletion ({label}): {len(targets)}")
    for r in targets[:10]:
        print(f"  - [{r.get('outcome')}] {str(r.get('claim'))[:70]}"
              f"  (made {r.get('made_on')} / resolved {r.get('resolved_on')})")
    if len(targets) > 10:
        print(f"  …and {len(targets) - 10} more")

    if not targets:
        print("Nothing to delete.")
        return 0
    if not args.apply:
        print("\nDRY RUN — nothing deleted. Re-run with --apply to delete "
              "(every deletion is tombstoned to prediction_tombstones).")
        return 0

    reason = REASON_ALL if args.all else REASON_PREMATURE
    try:
        deleted = _delete_rows(sb, targets, reason)
    except LedgerMaintenanceError as e:
        print(f"\nERROR: {e}")
        return 1
    print(f"\nDeleted {deleted} prediction(s) — each snapshotted to prediction_tombstones "
          f"(reason: {reason!r}). The scorecard will rebuild from what remains.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
