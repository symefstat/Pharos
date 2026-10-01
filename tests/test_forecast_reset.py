"""Tests for the forecast-ledger reset predicate and the tombstone-building
logic (pure — no network)."""

from forecast_reset import (
    REASON_ALL,
    REASON_PREMATURE,
    _days_between,
    _is_missing_rpc_error,
    _is_missing_table_error,
    build_tombstones,
    is_premature_resolution,
)


def test_days_between():
    assert _days_between("2026-06-12", "2026-06-12") == 0
    assert _days_between("2026-06-12", "2026-06-19") == 7
    assert _days_between("2026-06-12", None) is None       # unparseable → None


def test_flags_only_prematurely_resolved_auto_rows():
    same_day = {"status": "resolved", "kind": "posture_persist",
                "made_on": "2026-06-12", "resolved_on": "2026-06-12"}
    assert is_premature_resolution(same_day) is True       # 0 < 7 days

    # resolved after a real interval → genuine, keep it
    matured = {"status": "resolved", "kind": "deal_flow",
               "made_on": "2026-06-12", "resolved_on": "2026-07-01"}
    assert is_premature_resolution(matured) is False        # 19 >= 7 days

    # manual (Strategist, hand-graded) is never an artifact
    manual = {"status": "resolved", "kind": "manual",
              "made_on": "2026-06-12", "resolved_on": "2026-06-12"}
    assert is_premature_resolution(manual) is False

    # open forecasts are never flagged
    open_ = {"status": "open", "kind": "deal_flow", "made_on": "2026-06-12"}
    assert is_premature_resolution(open_) is False


# ── tombstones — deletions are snapshotted, never silent ──────────────────────

def test_build_tombstones_full_snapshot_with_reason():
    rows = [
        {"id": 1, "fingerprint": "aaa", "claim": "X happens", "status": "resolved",
         "outcome": "hit", "made_on": "2026-06-12", "resolved_on": "2026-06-12",
         "params": {"threshold": 3}},
        {"id": 2, "fingerprint": "bbb", "claim": "Y happens", "status": "open"},
    ]
    tombs = build_tombstones(rows, REASON_PREMATURE)
    assert len(tombs) == 2
    # the FULL original row rides in `original` — nothing dropped
    assert tombs[0]["original"] == rows[0]
    assert tombs[0]["original"]["params"] == {"threshold": 3}
    assert tombs[1]["original"]["fingerprint"] == "bbb"
    # every tombstone carries the reason
    assert all(t["reason"] == REASON_PREMATURE for t in tombs)
    # snapshots are copies: mutating the source afterwards can't rewrite them
    rows[0]["outcome"] = "miss"
    assert tombs[0]["original"]["outcome"] == "hit"


def test_build_tombstones_reasons_and_empty():
    assert build_tombstones([], REASON_ALL) == []
    tombs = build_tombstones([{"id": 9}], REASON_ALL)
    assert tombs == [{"original": {"id": 9}, "reason": "--all reset"}]
    assert REASON_PREMATURE == "premature-resolution cleanup"


# ── degradation predicates (mirror db.is_missing_column_error) ────────────────

def test_missing_rpc_error_predicate():
    missing = Exception("Could not find the function public.ledger_maintenance_delete"
                        "(p_ids, p_reason) in the schema cache (PGRST202)")
    assert _is_missing_rpc_error(missing) is True
    # a real failure inside the RPC must NOT be mistaken for a missing RPC
    real = Exception("ledger_maintenance_delete: a non-empty reason is required")
    assert _is_missing_rpc_error(real) is False
    unrelated = Exception("function foo() does not exist")
    assert _is_missing_rpc_error(unrelated) is False


def test_missing_table_error_predicate():
    missing = Exception('relation "prediction_tombstones" does not exist (42P01)')
    assert _is_missing_table_error(missing, "prediction_tombstones") is True
    other = Exception("duplicate key value violates unique constraint on "
                      "prediction_tombstones")
    assert _is_missing_table_error(other, "prediction_tombstones") is False
