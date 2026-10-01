-- Emergence map reference dots: every tracked technology's evidence
-- coordinates (stories/30d + arXiv papers/30d) captured at scan time, on the
-- SAME axes candidates are measured on — so the Radar page can plot "where
-- would this candidate sit among what we already track?" without fetching
-- arXiv on page load. Fail-open: analytics/radar.py retries the scan-log
-- insert without this column when it is missing.
ALTER TABLE radar_scans ADD COLUMN IF NOT EXISTS tracked_coords JSONB;
