-- ============================================================================
-- predictions — resolution evidence snapshot.
--   resolution_evidence — JSONB capturing what the resolver actually saw at the
--       moment a forecast was graded (the stage history, the sector tilt, the deal
--       count, the measured price moves, …), so the verdict is REPRODUCIBLE and
--       auditable after the source feed rows prune (14–30d). Without it, re-running
--       resolution reads a window that may have lost the confirming rows — biased
--       toward miss and non-reproducible. NULL on rows resolved before this column.
-- Written by forecast_run.py (resolve) via analytics/forecasts.py::resolution_evidence.
-- Idempotent; safe to re-run. The resolver degrades (resolves without the snapshot)
-- until it's applied. Apply AFTER predictions.sql.
-- ============================================================================

ALTER TABLE predictions ADD COLUMN IF NOT EXISTS resolution_evidence JSONB;
