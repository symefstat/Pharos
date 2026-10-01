-- Per-company fundamentals snapshot (free, via yfinance) for the 💰 Capital tab.
-- One row per tracked entity (see tickers.py); refreshed by financials_run.py.
-- rd_intensity is a ratio, so mixed-currency filings stay comparable. A NULL means
-- "unknown" — never treat it as zero. No subscription / API key required.
CREATE TABLE IF NOT EXISTS company_financials (
    entity        TEXT PRIMARY KEY,            -- canonical entity name (entities.normalize)
    symbol        TEXT NOT NULL,               -- yfinance ticker
    currency      TEXT,
    market_cap    DOUBLE PRECISION,
    revenue       DOUBLE PRECISION,            -- latest annual
    rd_expense    DOUBLE PRECISION,            -- latest annual R&D
    rd_intensity  DOUBLE PRECISION,            -- rd_expense / revenue
    capex         DOUBLE PRECISION,            -- latest annual capex (absolute)
    cash          DOUBLE PRECISION,            -- cash & equivalents
    as_of         DATE NOT NULL,               -- snapshot date
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
