-- Commissioned Analyst reports — the "analysis that will be graded" surface.
-- One row per commission (analytics/analyst.py run_analysis): the validated
-- report prose, the parsed posture block (whose central call can be locked
-- into the forecast ledger), database-computed exhibits (rendered natively —
-- the agent never draws), and the checkable story citations.
CREATE TABLE IF NOT EXISTS analyst_reports (
    id             BIGSERIAL PRIMARY KEY,
    topic          TEXT NOT NULL,
    report         TEXT NOT NULL,               -- markdown, ≤550 words by contract
    posture        JSONB NOT NULL,              -- {posture,addressee,confidence,falsifier,resolve_by}
    exhibits       JSONB NOT NULL,              -- {mention_trend,stage_table,capital_split,players,funding}
    citations      JSONB NOT NULL,              -- [{label,title,url,feed,published_at}]
    coverage       TEXT NOT NULL,               -- 'adequate' | 'thin'
    as_of          DATE NOT NULL,
    created_by     TEXT NOT NULL,               -- admin username from the auth token
    prompt_version TEXT NOT NULL,
    -- set when the central call is locked into the ledger ("log this call")
    ledger_pred_id BIGINT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analyst_reports_created
    ON analyst_reports (created_at DESC);
