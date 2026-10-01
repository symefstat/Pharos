"""financials_run — FX provenance stamping + pending-column degrade (no network/DB).

migrations/2026-07-03_fx_asof.sql adds optional columns (fx_source, fx_as_of,
rd_basis) to company_financials; until the user applies it, the upsert must strip
them and retry — mirroring home_news/writer's provenance degrade — so a financials
run never breaks on a pending migration.
"""

import logging

import net
import financials_run as fr
from analytics.financials import FX_AS_OF


def _no_sleep_retry(monkeypatch):
    # Exercise the real retry, but no-op the backoff sleep so tests are instant.
    orig = net.retry
    monkeypatch.setattr(net, "retry", lambda fn, **kw: orig(fn, sleep=lambda _s: None, **kw))


class _FakeSupabase:
    """Chainable sb.table(t).upsert(rows, on_conflict=…).execute() double. Raises a
    PostgREST-style missing-column error while rows still carry `missing_col`
    (i.e. until the caller strips it), or a hard error unconditionally."""

    def __init__(self, missing_col=None, hard_error=None):
        self.missing_col = missing_col
        self.hard_error = hard_error
        self.attempts = []          # rows passed to each upsert attempt
        self.written = None         # rows of the successful attempt

    def table(self, name):
        return self

    def upsert(self, rows, on_conflict=None):
        self._rows = rows
        return self

    def execute(self):
        self.attempts.append(self._rows)
        if self.hard_error:
            raise RuntimeError(self.hard_error)
        if self.missing_col and any(self.missing_col in r for r in self._rows):
            raise RuntimeError(
                "{'code': 'PGRST204', 'message': \"Could not find the "
                f"'{self.missing_col}' column of 'company_financials' in the schema cache\"}}"
            )
        self.written = self._rows
        return self


_ROWS = [{"entity": "Toyota", "symbol": "TM", "currency": "USD", "market_cap": 1.0,
          "fx_source": "yfinance", "fx_as_of": "2026-07-02", "rd_basis": None}]


def test_upsert_degrades_when_fx_columns_are_pending(monkeypatch, caplog):
    _no_sleep_retry(monkeypatch)
    sb = _FakeSupabase(missing_col="fx_as_of")
    with caplog.at_level(logging.WARNING, logger="financials_run"):
        n = fr._upsert(sb, "company_financials", [dict(r) for r in _ROWS], "entity",
                       optional_cols=fr._OPTIONAL_FIN_COLS)
    assert n == 1                                              # the base row still lands
    assert sb.written is not None
    for col in fr._OPTIONAL_FIN_COLS:                          # optional cols stripped…
        assert all(col not in r for r in sb.written)
    assert sb.written[0]["entity"] == "Toyota"                 # …but the payload survives
    assert "migrations/2026-07-03_fx_asof.sql" in caplog.text  # warning names the fix


def test_upsert_does_not_mask_real_failures(monkeypatch):
    # A failure that merely isn't about the optional columns must NOT trigger the
    # strip-and-retry — it degrades to 0 written (partial-success semantics).
    _no_sleep_retry(monkeypatch)
    sb = _FakeSupabase(hard_error="connection reset by peer")
    n = fr._upsert(sb, "company_financials", [dict(r) for r in _ROWS], "entity",
                   optional_cols=fr._OPTIONAL_FIN_COLS)
    assert n == 0 and sb.written is None


def test_upsert_writes_optional_columns_once_migration_applied(monkeypatch):
    _no_sleep_retry(monkeypatch)
    sb = _FakeSupabase()                                       # migration applied
    n = fr._upsert(sb, "company_financials", [dict(r) for r in _ROWS], "entity",
                   optional_cols=fr._OPTIONAL_FIN_COLS)
    assert n == 1 and sb.written[0]["fx_as_of"] == "2026-07-02"
    assert len(sb.attempts) == 1                               # no degrade round-trip


def test_fx_provenance_live_fallback_and_usd_only():
    live = {"rates": {"EUR": 1.14}, "as_of": "2026-07-02", "source": "yfinance"}
    assert fr._fx_provenance(live, {"USD", "EUR"}) == ("yfinance", "2026-07-02")
    dead = {"rates": {}, "as_of": None, "source": "yfinance"}
    # Live fetch failed with non-USD reporters in play → the dated static map.
    assert fr._fx_provenance(dead, {"USD", "JPY"}) == ("static-fallback", FX_AS_OF)
    # All-USD universe → no FX involved, nothing to stamp.
    assert fr._fx_provenance(dead, {"USD"}) == (None, None)
