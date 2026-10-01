-- Tombstones for the forecast ledger (Phase 2.6 — ledger durability).
--
-- Every deliberate deletion of a prediction leaves a full-row snapshot here —
-- deletions are tombstoned, never silent. Combined with the immutability
-- trigger (predictions_immutability.sql) this turns "we don't rewrite history"
-- from a promise into a property: rows can't be deleted without the
-- maintenance hatch, and the sanctioned path through the hatch writes the
-- tombstone in the same transaction as the delete.
--
-- The table is append-only: its own guard trigger blocks all UPDATE/DELETE,
-- no escape hatch.
--
-- ledger_maintenance_delete(p_ids, p_reason) is the ONE sanctioned deletion
-- path (forecast_reset.py calls it via supabase-py's .rpc()). PostgREST runs
-- each request in a single transaction and offers no way to issue a bare
-- SET LOCAL that survives into a later request, so the function bundles the
-- three steps atomically:
--   1. snapshot every targeted row into prediction_tombstones (with a reason),
--   2. SET LOCAL app.ledger_maintenance = 'on' (transaction-scoped — never
--      leaks past COMMIT/ROLLBACK),
--   3. delete the rows (the immutability guard sees the GUC and lets it pass).
--
-- Apply this file BEFORE predictions_immutability.sql. Idempotent; safe to re-run.

CREATE TABLE IF NOT EXISTS prediction_tombstones (
    id          BIGSERIAL PRIMARY KEY,
    original    JSONB NOT NULL,         -- the full deleted predictions row
    reason      TEXT NOT NULL,          -- e.g. 'premature-resolution cleanup', '--all reset'
    deleted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS prediction_tombstones_deleted_at_idx
    ON prediction_tombstones (deleted_at);

ALTER TABLE prediction_tombstones DISABLE ROW LEVEL SECURITY;

-- Append-only: tombstones themselves can never be edited or removed.
CREATE OR REPLACE FUNCTION prediction_tombstones_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'prediction_tombstones is append-only — % blocked (id %)', TG_OP, OLD.id;
END $$;

DROP TRIGGER IF EXISTS prediction_tombstones_append_only ON prediction_tombstones;
CREATE TRIGGER prediction_tombstones_append_only
    BEFORE UPDATE OR DELETE ON prediction_tombstones
    FOR EACH ROW EXECUTE FUNCTION prediction_tombstones_guard();

-- The sanctioned deletion path: tombstone + maintenance GUC + delete, one
-- transaction. Returns the number of predictions deleted.
CREATE OR REPLACE FUNCTION ledger_maintenance_delete(p_ids BIGINT[], p_reason TEXT)
RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    n INTEGER;
BEGIN
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'ledger_maintenance_delete: a non-empty reason is required';
    END IF;

    -- Tombstone FIRST — if anything below fails, the whole transaction rolls
    -- back and neither the snapshots nor the deletions happen.
    INSERT INTO prediction_tombstones (original, reason)
        SELECT to_jsonb(p), p_reason FROM predictions p WHERE p.id = ANY(p_ids);

    -- SET LOCAL: opens the immutability guard for THIS transaction only.
    PERFORM set_config('app.ledger_maintenance', 'on', true);

    DELETE FROM predictions WHERE id = ANY(p_ids);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;
