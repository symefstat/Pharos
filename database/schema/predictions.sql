-- Forecast ledger for the 🔮 Forecasts tab: accountable, falsifiable predictions
-- — locked once made and resolved objectively (auto against our own data where
-- machine-checkable, manual for judgment calls). Maintained by forecast_run.py.
-- `fingerprint` is UNIQUE so generation is idempotent (re-runs never duplicate).
CREATE TABLE IF NOT EXISTS predictions (
    id              BIGSERIAL PRIMARY KEY,
    fingerprint     TEXT NOT NULL UNIQUE,
    claim           TEXT NOT NULL,
    kind            TEXT NOT NULL,        -- stage_advance | posture_persist | deal_flow | manual
    subject         TEXT,                 -- tech key / sector / lens the claim is about
    horizon         TEXT NOT NULL,        -- short | long
    source          TEXT NOT NULL,        -- quant | strategist | manual
    confidence      DOUBLE PRECISION,     -- 0..1 (calibration is judged against this)
    basis           TEXT,                 -- what the forecast rests on
    params          JSONB NOT NULL DEFAULT '{}',
    made_on         DATE NOT NULL,
    resolve_by      DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    outcome         TEXT,                 -- hit | miss | partial
    resolved_on     DATE,
    resolution_note TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS predictions_status_idx ON predictions (status, resolve_by);
CREATE INDEX IF NOT EXISTS predictions_kind_subject_idx ON predictions (kind, subject);

ALTER TABLE predictions DISABLE ROW LEVEL SECURITY;
