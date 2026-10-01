"""
Free financial data integration (no API key, no subscription).

`client` wraps yfinance into plain-dict fundamentals snapshots and daily price
series. The `financials_run.py` job writes these into Supabase; the 💰 Capital tab
and `analytics.financials` reducers read them back. Network lives here only —
everything degrades to None / [] on failure so the app never shows fake numbers.
"""
