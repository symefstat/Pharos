"""Tests for the run-ledger: pure build_record + RunLedger.record with a fake
Supabase client (write path + the degrade-on-missing-table path). No network."""

from analytics.run_ledger import RunLedger, _is_missing_table_error, build_record


# ── build_record (pure) ──────────────────────────────────────────────────────

def test_build_record_normal():
    r = build_record("parse", "ev", {"parsed": 5, "received": 6}, ok=True)
    assert r == {"stage": "parse", "feed": "ev", "ok": True,
                 "metrics": {"parsed": 5, "received": 6}, "error": None}


def test_build_record_none_feed_and_metrics():
    r = build_record("rollup", None, None)
    assert r["feed"] is None and r["metrics"] == {} and r["ok"] is True


def test_build_record_error_coerced_to_str():
    r = build_record("lens", "chips", {}, ok=False, error=RuntimeError("boom"))
    assert r["ok"] is False and r["error"] == "boom"


def test_build_record_copies_metrics():
    m = {"a": 1}
    r = build_record("parse", "ev", m)
    r["metrics"]["a"] = 99
    assert m["a"] == 1  # the record holds its own dict, not the caller's


# ── _is_missing_table_error (pure) ───────────────────────────────────────────

def test_missing_table_signatures():
    assert _is_missing_table_error(Exception('relation "feed_runs" does not exist'))
    assert _is_missing_table_error(Exception("Could not find feed_runs in the schema cache"))
    assert _is_missing_table_error(Exception("PGRST205: feed_runs not found"))


def test_not_missing_table_when_no_signature():
    # mentions the table but it's a different failure → must NOT be swallowed
    assert not _is_missing_table_error(Exception("feed_runs row violates constraint"))


def test_not_missing_table_when_other_relation():
    assert not _is_missing_table_error(Exception('relation "other" does not exist'))


# ── RunLedger.record with a fake client ──────────────────────────────────────

class _FakeExec:
    def __init__(self, raise_exc=None):
        self._raise = raise_exc

    def execute(self):
        if self._raise:
            raise self._raise
        return type("Resp", (), {"data": [{}]})()


class _FakeTable:
    def __init__(self, parent):
        self.parent = parent

    def insert(self, row):
        self.parent.inserted.append(row)
        return _FakeExec(self.parent.raise_exc)


class _FakeClient:
    def __init__(self, raise_exc=None):
        self.inserted = []
        self.raise_exc = raise_exc
        self.last_table = None

    def table(self, name):
        self.last_table = name
        return _FakeTable(self)


def test_record_writes_row():
    client = _FakeClient()
    ok = RunLedger(client).record("parse", "ev", {"parsed": 3})
    assert ok is True
    assert client.last_table == "feed_runs"
    assert client.inserted == [{"stage": "parse", "feed": "ev", "ok": True,
                                "metrics": {"parsed": 3}, "error": None}]


def test_record_degrades_on_missing_table():
    client = _FakeClient(raise_exc=Exception('relation "feed_runs" does not exist'))
    assert RunLedger(client).record("parse", "ev", {}) is False  # no raise


def test_record_swallows_other_errors():
    client = _FakeClient(raise_exc=Exception("connection reset"))
    assert RunLedger(client).record("lens", "chips", {}) is False  # logged, not raised
