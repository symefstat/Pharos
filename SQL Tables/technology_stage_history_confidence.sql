-- ============================================================================
-- technology_stage_history — lens-confidence columns
-- Carries the MOT-lens placement confidence the analytics already compute
-- (analytics/tech_layer.py `_dimension_stats`) but used to drop before persistence.
--   maturity_modal_share / adoption_modal_share — REAL in [0,1]: the share of
--       on-curve articles in the modal stage that day (1.0 = unanimous).
--   maturity_mixed / adoption_mixed — BOOLEAN: TRUE when the placement is
--       contested (no clear majority, or the centroid sits off the modal stage).
-- Lets detect_transitions downrank a low-confidence (contested) stage flip instead
-- of headlining a 2-vs-1 plurality as a "decisive transition".
--
-- Idempotent; safe to re-run. Apply AFTER technology_stage_history.sql. Rows that
-- predate it stay NULL — the reader (detect_transitions) treats NULL as
-- not-contested/unknown, so old history degrades cleanly.
-- ============================================================================

ALTER TABLE technology_stage_history ADD COLUMN IF NOT EXISTS maturity_modal_share REAL;
ALTER TABLE technology_stage_history ADD COLUMN IF NOT EXISTS maturity_mixed        BOOLEAN;
ALTER TABLE technology_stage_history ADD COLUMN IF NOT EXISTS adoption_modal_share  REAL;
ALTER TABLE technology_stage_history ADD COLUMN IF NOT EXISTS adoption_mixed        BOOLEAN;
