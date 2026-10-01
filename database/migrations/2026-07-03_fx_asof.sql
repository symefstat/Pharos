-- ============================================================================
-- company_financials — FX provenance + curated R&D basis (pending-column migration).
--
--   fx_source — where the FX rates behind this row's write-time USD normalization
--               came from: 'yfinance' (live batched fetch in financials_run.py)
--               or 'static-fallback' (the dated map in analytics/financials.py,
--               used only when the live fetch fails). NULL on rows written
--               before this column existed.
--   fx_as_of  — the as-of date of those rates (last close of the batched FX
--               pairs, or analytics.financials.FX_AS_OF for the fallback), so
--               the Capital tab can caption "FX as of <date> (<source>)" instead
--               of an undated source line.
--   rd_basis  — how rd_expense was obtained when it is NOT the yfinance income-
--               statement row, e.g. 'curated-override (20-F FY2026)' for filers
--               whose R&D line Yahoo doesn't carry at all (Toyota — see
--               finance/client.py RD_OVERRIDES). NULL = plain yfinance value.
--
-- Written by financials_run.py. Until this is applied, the writer degrades —
-- it strips these columns and retries the upsert (same pattern as the feed
-- tables' provenance column, SQL Tables/feed_provenance_column.sql) — so a
-- financials run never breaks on the pending migration; the columns simply
-- stay unpopulated and the UI keeps its undated caption.
--
-- Idempotent; safe to re-run. Apply AFTER `SQL Tables/company_financials.sql`.
-- ============================================================================

ALTER TABLE company_financials ADD COLUMN IF NOT EXISTS fx_source TEXT;
ALTER TABLE company_financials ADD COLUMN IF NOT EXISTS fx_as_of  DATE;
ALTER TABLE company_financials ADD COLUMN IF NOT EXISTS rd_basis  TEXT;
