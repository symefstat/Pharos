-- Daily ledger-digest anchors (Phase 2.6 — ledger durability).
--
-- The public ledger ships `ledger_digest` — sha256 of the canonical JSON of
-- the forecast rows (backend/app/ledger.py, DIGEST_RECIPE). That proves a
-- downloaded JSON matches the digest it came with, but on its own a rewrite
-- of history is undetectable after the fact: recompute and both change
-- together. This table anchors one digest per day (written by forecast_run.py
-- AFTER resolution, so it reflects the day's final state). The chain is
-- append-only — its guard trigger blocks all UPDATE/DELETE, no escape hatch —
-- so any later rewrite of past rows shows up as a mismatch between a
-- recomputed historical state and its stored anchor, and the anchored
-- row_count can only legitimately grow (barring tombstoned maintenance,
-- which is itself logged in prediction_tombstones).
--
-- `as_of` is UNIQUE so anchoring is idempotent — one anchor per day no matter
-- how often the job runs. Idempotent; safe to re-run.

CREATE TABLE IF NOT EXISTS ledger_digests (
    id          BIGSERIAL PRIMARY KEY,
    digest      TEXT NOT NULL,          -- sha256 hex of the day's ledger rows
    as_of       DATE NOT NULL UNIQUE,   -- the day the digest describes
    row_count   INTEGER NOT NULL,       -- forecasts covered by the digest
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ledger_digests DISABLE ROW LEVEL SECURITY;

-- Append-only: anchors can never be edited or removed.
CREATE OR REPLACE FUNCTION ledger_digests_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'ledger_digests is append-only — % blocked (as_of %)', TG_OP, OLD.as_of;
END $$;

DROP TRIGGER IF EXISTS ledger_digests_append_only ON ledger_digests;
CREATE TRIGGER ledger_digests_append_only
    BEFORE UPDATE OR DELETE ON ledger_digests
    FOR EACH ROW EXECUTE FUNCTION ledger_digests_guard();
