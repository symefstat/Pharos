-- Recent daily closes per tracked ticker (free, via yfinance), powering the
-- event-reaction read on the 💰 Capital tab ("did the market agree this deal was
-- material?"). ~4 months retained per symbol; refreshed by financials_run.py.
-- Composite key (symbol, day) makes the upsert idempotent. No API key required.
CREATE TABLE IF NOT EXISTS stock_prices (
    symbol     TEXT NOT NULL,
    day        DATE NOT NULL,
    close      DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, day)
);

CREATE INDEX IF NOT EXISTS stock_prices_symbol_day_idx ON stock_prices (symbol, day DESC);
