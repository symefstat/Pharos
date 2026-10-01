-- Ledger immutability at the DATABASE level (Phase 2.6 — ledger durability).
--
-- Until now "locked once made" was an app-layer convention: predictions has RLS
-- disabled, so anyone holding the service key could UPDATE or DELETE resolved
-- rows and the public track record would silently rewrite. This trigger makes
-- the guarantee real: once a row is resolved, its record fields (claim,
-- confidence, made_on, resolve_by, status, outcome, resolved_on,
-- resolution_note) can no longer be modified, and the row can no longer be
-- deleted — the service key alone can no longer silently rewrite history.
--
-- What still passes:
--   * any UPDATE of an OPEN row — resolution itself (open → resolved) is an
--     update of an open row, so forecast_run.py keeps working unchanged;
--   * UPDATEs of a resolved row that leave every protected field untouched
--     (e.g. backfilling params/resolution_evidence-style metadata).
--
-- Escape hatch (deliberate, logged maintenance ONLY):
--   SET LOCAL app.ledger_maintenance = 'on';
-- inside the same transaction disables the guard for that transaction only
-- (SET LOCAL never leaks past COMMIT/ROLLBACK). Any use of it MUST be
-- accompanied by tombstones in prediction_tombstones (see
-- predictions_tombstones.sql — its ledger_maintenance_delete() RPC bundles
-- tombstone + SET LOCAL + delete in one transaction and is the sanctioned
-- path; forecast_reset.py calls it). PostgREST runs each request in its own
-- transaction, so a bare SET LOCAL over the API does nothing — the hatch is
-- only reachable through that RPC or the Supabase SQL editor.
--
-- Apply AFTER predictions_tombstones.sql (so the sanctioned deletion path
-- exists before deletions start being blocked). Idempotent; safe to re-run.

CREATE OR REPLACE FUNCTION predictions_immutability_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Maintenance escape hatch: transaction-scoped, must be tombstoned.
    IF current_setting('app.ledger_maintenance', true) = 'on' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'resolved' THEN
            RAISE EXCEPTION
                'predictions: resolved ledger rows are immutable — DELETE of id % blocked. '
                'Deliberate maintenance must tombstone first: use ledger_maintenance_delete() '
                '(SQL Tables/predictions_tombstones.sql) or SET LOCAL app.ledger_maintenance = ''on'' '
                'in the SQL editor.', OLD.id;
        END IF;
        RETURN OLD;  -- deleting an OPEN row is allowed
    END IF;

    -- UPDATE: open rows pass freely (resolution is open → resolved);
    -- resolved rows may not change any field of the locked record.
    IF OLD.status = 'resolved' AND (
        NEW.status          IS DISTINCT FROM OLD.status OR
        NEW.outcome         IS DISTINCT FROM OLD.outcome OR
        NEW.resolved_on     IS DISTINCT FROM OLD.resolved_on OR
        NEW.resolution_note IS DISTINCT FROM OLD.resolution_note OR
        NEW.claim           IS DISTINCT FROM OLD.claim OR
        NEW.confidence      IS DISTINCT FROM OLD.confidence OR
        NEW.made_on         IS DISTINCT FROM OLD.made_on OR
        NEW.resolve_by      IS DISTINCT FROM OLD.resolve_by
    ) THEN
        RAISE EXCEPTION
            'predictions: resolved ledger rows are immutable — UPDATE of id % blocked '
            '(status/outcome/resolved_on/resolution_note/claim/confidence/made_on/resolve_by '
            'are locked once resolved). Deliberate maintenance requires SET LOCAL '
            'app.ledger_maintenance = ''on'' in the same transaction, plus a tombstone.', OLD.id;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS predictions_immutability ON predictions;
CREATE TRIGGER predictions_immutability
    BEFORE UPDATE OR DELETE ON predictions
    FOR EACH ROW EXECUTE FUNCTION predictions_immutability_guard();
