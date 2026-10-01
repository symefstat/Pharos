"""_stage_segments — the RLE behind /api/mot/history (pure)."""

from backend.app.mot import _stage_segments


def _snap(as_of, maturity=None):
    return {"as_of": as_of, "maturity_stage": maturity}


def test_consecutive_same_stage_collapses_into_one_segment():
    snaps = [_snap("2026-07-01", "emerging"), _snap("2026-07-02", "emerging"),
             _snap("2026-07-03", "emerging")]
    segs = _stage_segments(snaps, "maturity_stage")
    assert segs == [{"stage": "emerging", "from": "2026-07-01", "to": "2026-07-03", "snapshots": 3}]


def test_stage_change_starts_a_new_segment():
    snaps = [_snap("2026-07-01", "emerging"), _snap("2026-07-02", "growth")]
    segs = _stage_segments(snaps, "maturity_stage")
    assert [s["stage"] for s in segs] == ["emerging", "growth"]
    assert segs[0]["to"] == "2026-07-01" and segs[1]["from"] == "2026-07-02"


def test_flip_back_yields_three_segments_not_a_merge():
    snaps = [_snap("2026-07-01", "emerging"), _snap("2026-07-02", "growth"),
             _snap("2026-07-03", "emerging")]
    assert [s["stage"] for s in _stage_segments(snaps, "maturity_stage")] == [
        "emerging", "growth", "emerging"]


def test_unclassified_days_are_gaps_not_stage_claims():
    # NULL stage (below evidence floor / no coverage) extends nothing; the
    # same stage on the far side of the gap still extends the open segment.
    snaps = [_snap("2026-07-01", "emerging"), _snap("2026-07-02", None),
             _snap("2026-07-03", "emerging")]
    segs = _stage_segments(snaps, "maturity_stage")
    assert segs == [{"stage": "emerging", "from": "2026-07-01", "to": "2026-07-03", "snapshots": 2}]


def test_empty_and_all_null_histories_yield_no_segments():
    assert _stage_segments([], "maturity_stage") == []
    assert _stage_segments([_snap("2026-07-01", None)], "maturity_stage") == []
