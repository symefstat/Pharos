# Ledger durability (Phase 2.6)

The forecast ledger's "locked once made" promise used to be an app-layer
convention only: `predictions` has RLS disabled, so the service key could
UPDATE/DELETE resolved rows silently, `forecast_reset.py` could hard-delete
history with no trace, and past digests were never anchored anywhere — a
rewrite was undetectable after the fact. These three files close that.

## What to apply (Supabase SQL editor, in this order)

1. **`predictions_tombstones.sql`** — the append-only `prediction_tombstones`
   table plus the `ledger_maintenance_delete(p_ids, p_reason)` RPC, the one
   sanctioned deletion path (tombstone → `SET LOCAL app.ledger_maintenance =
   'on'` → delete, in a single transaction). Apply first so the sanctioned
   path exists before deletions start being blocked.
2. **`predictions_immutability.sql`** — the trigger that blocks UPDATE of any
   locked field (status/outcome/resolved_on/resolution_note/claim/confidence/
   made_on/resolve_by) on a resolved row, and DELETE of any resolved row.
   Open rows update freely, so resolution (open → resolved) keeps working.
3. **`ledger_digests.sql`** — the append-only daily digest-anchor table.
   `forecast_run.py` anchors one digest per day after resolution (idempotent,
   non-fatal if the table is missing).

All three are idempotent — safe to re-run.

## The maintenance escape hatch

Deliberate maintenance (e.g. the documented premature-resolution cleanup in
`forecast_reset.py`) goes through `ledger_maintenance_delete()`, which
tombstones every row before deleting it. If you must operate manually, run in
the SQL editor inside one transaction:

```sql
BEGIN;
INSERT INTO prediction_tombstones (original, reason)
    SELECT to_jsonb(p), 'why you are doing this' FROM predictions p WHERE <target>;
SET LOCAL app.ledger_maintenance = 'on';
DELETE FROM predictions WHERE <target>;
COMMIT;
```

`SET LOCAL` is transaction-scoped and never leaks. Never use the hatch
without writing tombstones — the tombstone IS the audit trail. PostgREST runs
each API request in its own transaction, so the hatch is unreachable through
the REST API except via the RPC above.

## How digest anchoring makes tampering detectable

`/api/ledger` ships `ledger_digest` (sha256 of the canonical JSON of the
forecast rows — recipe in the payload). Each day `forecast_run.py` also
anchors that digest into `ledger_digests` (append-only, one row per day,
UNIQUE `as_of`). The payload exposes the last ~30 anchors as
`digest_history`. Because the chain can only be appended to:

- today's recomputed digest must match today's anchor;
- any rewrite of past rows changes the recomputed digest away from the
  already-stored anchors — a mismatch that cannot be repaired, because
  anchors can't be edited or deleted;
- legitimate maintenance deletions also break old anchors, but they are
  explained by matching rows in `prediction_tombstones`. A digest mismatch
  with no tombstone is tampering.

## Backups (recommended)

Enable Supabase **Point-in-Time Recovery** (or at minimum daily scheduled
backups) on this project. Triggers protect against silent rewrites through
the API/service key, but not against a dropped table or a compromised
dashboard session — PITR is the last line of defence, and it also lets you
recompute historical digests to verify the anchor chain end-to-end.
