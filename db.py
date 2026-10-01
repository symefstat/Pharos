"""
Process-wide Supabase client.

Both the Streamlit app and the CLI runners share one client instead of each
module calling create_client() on its own. The classes still accept an injected
`client=` for tests; when omitted they default to this singleton.

In Streamlit, Home.py wraps get_supabase() in @st.cache_resource so the same
client is reused across reruns (it is process-wide here too, so that wrapper is
mostly there to make the dependency explicit and idiomatic).
"""

from __future__ import annotations

from supabase import Client, create_client

from config import Config

_client: Client | None = None


def get_supabase() -> Client:
    """Return the shared Supabase client, creating it on first use."""
    global _client
    if _client is None:
        _client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    return _client


def is_missing_column_error(err: Exception, column: str) -> bool:
    """True if a write failed because `column` isn't in the table yet — i.e. an
    optional migration hasn't been applied. Lets writers degrade (drop the column
    and retry) so a run never breaks just because a new column is pending. Pure.

    Matches only the *specific* missing-column signatures: PostgREST schema-cache
    miss (PGRST204 — "could not find the '<col>' column … in the schema cache")
    or Postgres undefined-column (42703 — 'column "<col>" does not exist').
    Deliberately NOT the bare word "column": a value/constraint error that merely
    names the column would otherwise be mistaken for a missing column and mask a
    real failure behind the strip-and-retry."""
    msg = str(err).lower()
    if column.lower() not in msg:
        return False
    return any(tok in msg for tok in
               ("could not find", "does not exist", "schema cache", "pgrst204", "42703"))
