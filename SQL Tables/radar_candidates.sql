-- Radar candidates — technologies Lodestar does NOT track yet, surfaced from
-- the unmatched-story corpus. Proposed by the Scout agent
-- (Agents_prompt/Scout_Agent.md, TOQAN_SCOUT) or the deterministic tag
-- fallback, then evidence-gated in analytics/radar.py (≥5 stories, ≥3
-- sources, ≥7 days spread) before a row is written. An admin promotes a
-- candidate into tracked_technologies from the Radar page ("start tracking"),
-- or dismisses it; re-scans refresh evidence but never overwrite that verdict.
CREATE TABLE IF NOT EXISTS radar_candidates (
    key            TEXT PRIMARY KEY,                 -- slugified candidate name
    label          TEXT NOT NULL,                    -- display name, e.g. 'Solid-state cooling'
    keywords       JSONB NOT NULL,                   -- lowercase matching keywords (≤6)
    domain_hint    TEXT,                             -- suggested domain, or 'other'
    why            TEXT,                             -- scout one-liner (validated [S#] citations)
    evidence       JSONB NOT NULL,                   -- {mentions, sources, feeds, first_seen, last_seen, stories[]}
    status         TEXT NOT NULL DEFAULT 'new',      -- new | dismissed | promoted
    prompt_version TEXT,                             -- e.g. 'scout-v1'
    first_detected DATE NOT NULL,
    last_updated   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_radar_candidates_status
    ON radar_candidates (status, last_updated DESC);
