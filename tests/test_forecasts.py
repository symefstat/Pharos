"""Tests for the forecast ledger — generation, objective resolution, scoring (pure)."""

import analytics.forecasts as fc


# ── generation ────────────────────────────────────────────────────────────────
def test_gen_stage_advance_only_for_advanceable_with_coverage():
    placements = [
        {"tech": "glp-1-drugs", "label": "GLP-1 drugs", "adoption": "early-adopters", "articles": 12},
        {"tech": "fusion", "label": "Fusion", "adoption": "innovators", "articles": 2},   # too few
        {"tech": "lfp", "label": "LFP batteries", "adoption": "laggards", "articles": 9},  # no room
        {"tech": "x", "label": "X", "adoption": None, "articles": 9},                      # unknown
    ]
    out = fc.gen_stage_advance(placements, as_of="2026-06-12", min_articles=4)
    assert len(out) == 1
    p = out[0]
    assert p["subject"] == "glp-1-drugs" and p["kind"] == "stage_advance"
    assert p["params"]["from_index"] == 1 and p["horizon"] == "short"
    assert p["resolve_by"] == "2026-12-09"          # +180d (claim: "within ~2 quarters")
    assert 0.5 <= p["confidence"] <= 0.7


def test_gen_posture_persist_and_deal_flow():
    roll = [{"sector": "Chips", "commitment": 7, "option": 1},
            {"sector": "Energy", "commitment": 0, "option": 0}]          # no deals → skipped
    pp = fc.gen_posture_persist(roll, as_of="2026-06-12")
    assert len(pp) == 1 and pp[0]["params"]["tilt"] == "commitment"

    df = fc.gen_deal_flow({"Chips": 4, "Auto & EV": 1}, as_of="2026-06-12", threshold=2)
    assert len(df) == 1 and df[0]["subject"] == "Chips"
    assert df[0]["params"]["threshold"] == 2
    assert df[0]["resolve_by"] == "2026-07-12"       # +30d (claim: "within ~1 month")
    assert pp[0]["resolve_by"] == "2026-09-10"       # posture unchanged: "next quarter" = 90d


def test_gen_from_strategist_captures_signals_with_falsifier():
    brief = {"as_of": "2026-06-12", "strategic_read": {"signals": [
        {"title": "HBM crosses the chasm", "falsifier": "export volume stalls",
         "horizon": "near", "confidence": "high", "lens": "Chasm crossing"},
        {"title": "Dominant foundry design settles", "horizon": "structural",
         "confidence": "medium", "lens": "Standards battle"},
        {"no_title": True},                                              # skipped
    ]}}
    out = fc.gen_from_strategist(brief, as_of="2026-06-12")
    assert len(out) == 2
    a, b = out
    assert a["source"] == "strategist" and a["kind"] == "manual"
    assert "wrong if: export volume stalls" in a["claim"]
    assert a["horizon"] == "short" and a["confidence"] == 0.75
    assert b["horizon"] == "long" and b["confidence"] == 0.55           # structural → long


def test_fingerprints_are_stable_and_distinct():
    roll = [{"sector": "Chips", "commitment": 5, "option": 1}]
    a = fc.gen_posture_persist(roll, as_of="2026-06-12")[0]
    b = fc.gen_posture_persist(roll, as_of="2026-06-12")[0]
    c = fc.gen_posture_persist(roll, as_of="2026-06-13")[0]            # different day
    assert a["fingerprint"] == b["fingerprint"]                        # idempotent same day
    assert a["fingerprint"] != c["fingerprint"]                       # new cycle, new fp


# ── resolution ─────────────────────────────────────────────────────────────────
def test_resolve_stage_advance_hit_and_open():
    pred = {"subject": "glp-1-drugs", "made_on": "2026-06-12", "resolve_by": "2026-09-10",
            "params": {"from_index": 1}}            # from early-adopters (idx 1)
    hist_hit = [{"technology": "glp-1-drugs", "as_of": "2026-07-01", "adoption_stage": "early-majority"}]
    res = fc.resolve_stage_advance(pred, hist_hit)
    assert res and res[0] == "hit"
    # no advance yet → None (leave open)
    hist_flat = [{"technology": "glp-1-drugs", "as_of": "2026-07-01", "adoption_stage": "early-adopters"}]
    assert fc.resolve_stage_advance(pred, hist_flat) is None
    # advance outside the window doesn't count
    hist_late = [{"technology": "glp-1-drugs", "as_of": "2026-10-01", "adoption_stage": "late-majority"}]
    assert fc.resolve_stage_advance(pred, hist_late) is None
    # an advance recorded ON the made day doesn't count (must be strictly after)
    hist_sameday = [{"technology": "glp-1-drugs", "as_of": "2026-06-12", "adoption_stage": "late-majority"}]
    assert fc.resolve_stage_advance(pred, hist_sameday) is None


def test_resolve_posture_persist_is_duration_gated():
    pred = {"params": {"tilt": "commitment"}, "resolve_by": "2026-09-10"}
    # still commitment, but before resolve_by → OPEN (can't confirm persistence on day 0)
    assert fc.resolve_posture_persist(pred, "commitment", "2026-06-15") is None
    # still commitment at/after resolve_by → HIT
    assert fc.resolve_posture_persist(pred, "commitment", "2026-09-10")[0] == "hit"
    # flipped → MISS at any time (a valid early miss)
    assert fc.resolve_posture_persist(pred, "option", "2026-06-15")[0] == "miss"
    # unknown tilt → open
    assert fc.resolve_posture_persist(pred, None, "2026-09-10") is None


def test_resolve_deal_flow_and_overdue_and_elapsed():
    dp = {"params": {"threshold": 2}}
    assert fc.resolve_deal_flow(dp, 3)[0] == "hit"
    assert fc.resolve_deal_flow(dp, 1) is None
    assert fc.is_overdue({"resolve_by": "2026-06-01"}, "2026-06-12") is True
    assert fc.is_overdue({"resolve_by": "2026-09-01"}, "2026-06-12") is False
    # elapsed gate: forecasts can't bank a HIT in their first week
    assert fc.MIN_RESOLVE_DAYS == 7
    assert fc.elapsed_days({"made_on": "2026-06-12"}, "2026-06-12") == 0
    assert fc.elapsed_days({"made_on": "2026-06-12"}, "2026-06-19") == 7
    assert fc.elapsed_days({}, "2026-06-19") == 0          # unparseable → 0


# ── scoring ──────────────────────────────────────────────────────────────────--
def _r(conf, outcome):
    return {"status": "resolved", "confidence": conf, "outcome": outcome}


def test_accuracy_and_brier_and_track_record():
    resolved = [_r(0.8, "hit"), _r(0.6, "miss"), _r(0.5, "partial")]
    assert fc.accuracy(resolved) == round((1 + 0 + 0.5) / 3, 3)
    # brier = mean((.8-1)^2, (.6-0)^2, (.5-.5)^2) = (.04+.36+0)/3
    assert fc.brier_score(resolved) == round((0.04 + 0.36 + 0.0) / 3, 3)
    assert fc.accuracy([]) is None and fc.brier_score([]) is None
    tr = fc.track_record(resolved + [{"status": "open"}])
    assert tr["resolved"] == 3 and tr["open"] == 1 and tr["hits"] == 1


def test_gen_reactivity_and_price_move():
    react = fc.gen_reactivity({"Chips": 3, "Energy": 0}, as_of="2026-06-12")
    assert len(react) == 1 and react[0]["kind"] == "reactivity" and react[0]["subject"] == "Chips"
    assert react[0]["resolve_by"] == "2026-07-12"    # +30d (claim: "within ~1 month")

    series = [{"date": f"2026-0{m}-01", "close": c} for m, c in
              [(3, 100.0), (4, 104.0), (5, 108.0), (6, 112.0)]]            # +12% over lookback
    prices = {"NVDA": series}
    pm = fc.gen_price_move(prices, {"NVDA": "Nvidia"}, as_of="2026-06-12", lookback=2)
    assert len(pm) == 1
    assert pm[0]["kind"] == "price_move" and pm[0]["params"]["direction"] == "up"
    assert pm[0]["confidence"] == 0.5                                    # honest: near coin-flip


def test_resolve_reactivity_and_price_move():
    rp = {"params": {"threshold_pct": 2.0}}
    assert fc.resolve_reactivity(rp, [0.5, 3.1])[0] == "hit"
    assert fc.resolve_reactivity(rp, [0.5, -1.0]) is None
    # price: only resolves once data reaches resolve_by
    series = [{"date": "2026-06-12", "close": 100.0}, {"date": "2026-09-10", "close": 110.0}]
    pred = {"made_on": "2026-06-12", "resolve_by": "2026-09-10",
            "params": {"direction": "up", "threshold": 5.0}}
    res = fc.resolve_price_move(pred, series)
    assert res and res[0] == "hit" and "+10.0%" in res[1]
    # not enough forward data yet → None
    assert fc.resolve_price_move(pred, [{"date": "2026-06-12", "close": 100.0}]) is None
    # wrong direction → miss
    down = {"made_on": "2026-06-12", "resolve_by": "2026-09-10",
            "params": {"direction": "down", "threshold": 5.0}}
    assert fc.resolve_price_move(down, series)[0] == "miss"


def test_category_split_and_summary():
    preds = [
        {"kind": "price_move", "status": "resolved", "confidence": 0.5, "outcome": "miss"},
        {"kind": "price_move", "status": "resolved", "confidence": 0.5, "outcome": "hit"},
        {"kind": "stage_advance", "status": "resolved", "confidence": 0.6, "outcome": "hit"},
        {"kind": "stage_advance", "status": "open", "confidence": 0.6},
    ]
    cats = {c["category"]: c for c in fc.track_record_by_category(preds)}
    assert cats["Price (low-signal)"]["resolved"] == 2 and cats["Price (low-signal)"]["accuracy"] == 0.5
    assert cats["Technology"]["accuracy"] == 1.0
    assert fc.category_of("reactivity") == "Market reactivity"
    s = fc.forecast_summary(preds, fc.track_record(preds))
    assert "Forward view" in s


def test_headline_excludes_quarantined_price_calls():
    # The quarantine is real: resolved price calls do NOT move the pooled headline.
    core = [dict(_r(0.8, "hit"), kind="stage_advance") for _ in range(4)]
    price = [dict(_r(0.5, "miss"), kind="price_move") for _ in range(3)]
    price += [dict(_r(0.5, "hit"), kind="price_move")]
    tr_core, tr_all = fc.track_record(core), fc.track_record(core + price)
    assert tr_all["accuracy"] == tr_core["accuracy"] == 1.0     # coin flips can't drag it
    assert tr_all["brier"] == tr_core["brier"]
    assert tr_all["resolved"] == 4 and tr_all["hits"] == 4 and tr_all["misses"] == 0
    # counts reconcile: headline pool + quarantined == everything resolved
    assert tr_all["quarantined_resolved"] == 4
    assert tr_all["resolved"] + tr_all["quarantined_resolved"] == \
        sum(1 for p in core + price if p["status"] == "resolved")
    # the category breakout still scores them — quarantined means separated, not hidden
    cats = {c["category"]: c for c in fc.track_record_by_category(core + price)}
    assert cats["Price (low-signal)"]["resolved"] == 4
    assert cats["Price (low-signal)"]["accuracy"] == 0.25       # 1 hit of 4
    assert cats["Price (low-signal)"]["brier"] == 0.25          # pinned 0.5 → coin-flip Brier
    # every headline consumer inherits the exclusion via calibration_headline
    h = fc.calibration_headline(core + price)
    assert h["accuracy"] == 1.0 and h["resolved"] == 4 and h["quarantined_resolved"] == 4


def test_naive_baseline_mixed_pool_has_known_skill():
    # 3 hits @0.8 + 1 miss @0.6 → base rate 0.75; majority rule scores 0.75;
    # climatology Brier = 0.75·0.25 = 0.1875; record Brier = (3·0.04 + 0.36)/4 = 0.12
    # → skill = 1 − 0.12/0.1875 = +0.36; accuracy edge = 75% − 75% = 0.0pp.
    resolved = [_r(0.8, "hit"), _r(0.8, "hit"), _r(0.8, "hit"), _r(0.6, "miss")]
    nb = fc.naive_baseline(resolved)
    assert nb["base_rate"] == 0.75
    assert nb["baseline_accuracy"] == 0.75
    assert nb["baseline_brier"] == round(0.1875, 3)
    assert nb["brier_skill"] == 0.36
    assert nb["accuracy_edge_pp"] == 0.0


def test_naive_baseline_no_test_when_outcome_never_varies():
    # A 31/31 category (the market-reactivity shape): the baseline is unbeatable and
    # the climatology Brier is 0 — skill must be None ("no test"), never a number.
    allhits = [_r(0.6, "hit") for _ in range(31)]
    nb = fc.naive_baseline(allhits)
    assert nb["base_rate"] == 1.0 and nb["baseline_accuracy"] == 1.0
    assert nb["baseline_brier"] == 0.0
    assert nb["brier_skill"] is None                 # outcome never varies → undefined
    assert nb["accuracy_edge_pp"] == 0.0             # 100% accuracy IS the base rate
    # nothing resolved → every field None ('not computable', never 0)
    assert all(v is None for v in fc.naive_baseline([]).values())


def test_track_record_baseline_respects_quarantine_and_reconciles():
    core = [dict(_r(0.8, "hit"), kind="stage_advance") for _ in range(3)]
    core += [dict(_r(0.6, "miss"), kind="deal_flow")]
    price = [dict(_r(0.5, "miss"), kind="price_move") for _ in range(3)]
    tr = fc.track_record(core + price)
    # headline base rate is computed over the SAME quarantine-respecting pool as the
    # accuracy it sits next to — the 3 price misses don't drag it to 3/7
    assert tr["base_rate"] == tr["accuracy"] == 0.75
    assert tr["base_rate"] == fc.naive_baseline(core)["base_rate"]
    assert tr["baseline_accuracy"] == 0.75 and tr["accuracy_edge_pp"] == 0.0
    assert tr["brier_skill"] == 0.36
    # per-category rows carry their own baselines (price calls scored in their row)
    cats = {c["category"]: c for c in fc.track_record_by_category(core + price)}
    assert cats["Technology"]["base_rate"] == 1.0
    assert cats["Technology"]["brier_skill"] is None          # all-hit: no test yet
    assert cats["Price (low-signal)"]["base_rate"] == 0.0     # all-miss: also no test
    assert cats["Price (low-signal)"]["baseline_accuracy"] == 1.0
    assert cats["Price (low-signal)"]["brier_skill"] is None
    # headline reconciliation: calibration_headline inherits the same numbers
    h = fc.calibration_headline(core + price)
    assert h["base_rate"] == tr["base_rate"] and h["brier_skill"] == tr["brier_skill"]
    assert h["accuracy_edge_pp"] == tr["accuracy_edge_pp"]


def test_forecast_summary_withholds_headline_accuracy_below_floor():
    nine = [_r(0.8, "hit") for _ in range(9)]
    s9 = fc.forecast_summary(nine, fc.track_record(nine))
    assert "Track record:" not in s9 and "resolved so far" in s9   # building, no headline %
    ten = [_r(0.8, "hit") for _ in range(10)]
    s10 = fc.forecast_summary(ten, fc.track_record(ten))
    assert "Track record:" in s10 and "%" in s10                    # headline % unlocked at the floor


def test_calibration_tagline_withholds_accuracy_below_floor():
    # 'live' (≥4 resolved) shows the Brier verdict, but the swingy % waits for the floor.
    five = [dict(_r(0.8, "hit"), kind="stage_advance") for _ in range(5)]
    h5 = fc.calibration_headline(five)
    assert h5["state"] == "live"
    tag5 = fc.calibration_tagline(h5)
    assert "accurate across" not in tag5 and "Headline accuracy holds" in tag5
    ten = [dict(_r(0.8, "hit"), kind="stage_advance") for _ in range(10)]
    assert "accurate across" in fc.calibration_tagline(fc.calibration_headline(ten))


def test_resolution_evidence_snapshots_per_kind():
    # deal_flow / reactivity capture the counts/moves they saw (reproducible after prune)
    assert fc.resolution_evidence({"kind": "deal_flow", "subject": "Chips"}, deals=3)["deals_since"] == 3
    assert fc.resolution_evidence({"kind": "reactivity", "subject": "Chips"},
                                  moves=[12.0, -3.0])["moves_pct"] == [12.0, -3.0]
    # stage_advance filters the history to the subject's adoption stages
    sa = fc.resolution_evidence(
        {"kind": "stage_advance", "subject": "glp-1"},
        history=[{"technology": "glp-1", "adoption_stage": "early-majority"},
                 {"technology": "other", "adoption_stage": "growth"}])
    assert sa["stages_seen"] == ["early-majority"]
    # price_move summarises the series; posture_persist records the tilt
    pm = fc.resolution_evidence({"kind": "price_move", "subject": "NVDA"},
                                series=[{"date": "d1", "close": 100.0}, {"date": "d2", "close": 110.0}])
    assert pm["closes_seen"] == 2 and pm["last_close"] == 110.0
    pp = fc.resolution_evidence({"kind": "posture_persist", "subject": "Chips"}, tilt="commitment")
    assert pp["tilt_now"] == "commitment"


def test_realized_rates_over_resolved_only():
    preds = [
        {"kind": "deal_flow", "status": "resolved", "outcome": "hit", "confidence": 0.6},
        {"kind": "deal_flow", "status": "resolved", "outcome": "hit", "confidence": 0.6},
        {"kind": "deal_flow", "status": "resolved", "outcome": "miss", "confidence": 0.6},
        {"kind": "deal_flow", "status": "open", "confidence": 0.6},          # ignored
        {"kind": "stage_advance", "status": "resolved", "outcome": None},    # no valid outcome
    ]
    rates = fc.realized_rates(preds)
    assert rates["deal_flow"] == {"rate": round(2 / 3, 3), "n": 3}
    assert "stage_advance" not in rates                                     # only invalid outcomes


def test_recalibrated_confidence_shrinks_and_bounds():
    # No record for the kind → unchanged.
    assert fc.recalibrated_confidence(0.6, "deal_flow", {}) == 0.6
    # Thin record (n=2) barely moves the 0.6 prior toward a 1.0 realized rate.
    thin = fc.recalibrated_confidence(0.6, "deal_flow", {"deal_flow": {"rate": 1.0, "n": 2}})
    assert 0.6 < thin <= 0.7
    # Large record pulls harder, but the ±0.20 cap holds it at 0.80 (not 0.95).
    big = fc.recalibrated_confidence(0.6, "deal_flow", {"deal_flow": {"rate": 1.0, "n": 500}})
    assert big == 0.8
    # Poor realized rate pulls confidence down, floored by the cap.
    low = fc.recalibrated_confidence(0.6, "deal_flow", {"deal_flow": {"rate": 0.0, "n": 500}})
    assert low == 0.4


def test_apply_calibration_skips_price_and_manual():
    rates = {"deal_flow": {"rate": 1.0, "n": 50}, "price_move": {"rate": 0.9, "n": 50},
             "manual": {"rate": 0.9, "n": 50}}
    cands = [
        {"kind": "deal_flow", "confidence": 0.6, "basis": "x"},
        {"kind": "price_move", "confidence": 0.5, "basis": "pinned"},
        {"kind": "manual", "confidence": 0.55, "basis": "strategist"},
    ]
    out = {c["kind"]: c for c in fc.apply_calibration(cands, rates)}
    assert out["deal_flow"]["confidence"] == 0.8 and "recalibrated 60→80%" in out["deal_flow"]["basis"]
    assert out["price_move"]["confidence"] == 0.5 and out["price_move"]["basis"] == "pinned"
    assert out["manual"]["confidence"] == 0.55                              # untouched
    # input not mutated
    assert cands[0]["confidence"] == 0.6


def test_calibration_headline_states():
    # empty — nothing logged
    h = fc.calibration_headline([])
    assert h["state"] == "empty" and h["total"] == 0 and h["categories"] == []

    # seeded — open forecasts, none resolved
    seeded = [{"kind": "stage_advance", "status": "open", "confidence": 0.6},
              {"kind": "deal_flow", "status": "open", "confidence": 0.6}]
    h = fc.calibration_headline(seeded)
    assert h["state"] == "seeded" and h["open"] == 2 and h["resolved"] == 0

    # building — 1–3 resolved (under the verdict threshold)
    building = seeded + [_r(0.6, "hit"), _r(0.6, "miss")]
    for p in building[-2:]:
        p["kind"] = "stage_advance"
    h = fc.calibration_headline(building)
    assert h["state"] == "building" and h["resolved"] == 2
    assert h["verdict"] == "calibration still building"          # <4 resolved

    # live — ≥4 resolved unlocks the full verdict + per-category cut
    live = [dict(_r(0.8, "hit"), kind="stage_advance") for _ in range(4)]
    live += [dict(_r(0.5, "miss"), kind="price_move")]
    h = fc.calibration_headline(live)
    assert h["state"] == "live" and h["resolved"] == 4          # price call quarantined
    assert h["quarantined_resolved"] == 1
    cats = {c["category"]: c for c in h["categories"]}
    assert cats["Technology"]["accuracy"] == 1.0
    assert cats["Price (low-signal)"]["resolved"] == 1           # walled off, still visible
    assert "verdict" in cats["Technology"]


def test_calibration_headline_resolved_but_unscored_is_not_live():
    # ≥4 rows marked resolved but with no valid outcome (e.g. a NULL outcome left by
    # a half-finished manual resolution) → accuracy/Brier are None, so it must NOT be
    # 'live' (which would crash the tagline on None * 100).
    unscored = [{"kind": "stage_advance", "status": "resolved", "confidence": 0.7,
                 "outcome": None} for _ in range(4)]
    h = fc.calibration_headline(unscored)
    assert h["resolved"] == 4 and h["accuracy"] is None
    assert h["state"] == "building"                      # not 'live'
    fc.calibration_tagline(h)                            # must not raise


def test_calibration_tagline_per_state():
    assert "starts with the first" in fc.calibration_tagline(fc.calibration_headline([]))
    seeded = [{"kind": "deal_flow", "status": "open", "confidence": 0.6}]
    assert "on the clock" in fc.calibration_tagline(fc.calibration_headline(seeded))
    building = [dict(_r(0.6, "hit"), kind="stage_advance")]
    assert "resolved so far" in fc.calibration_tagline(fc.calibration_headline(building))
    # 'live' (≥4) shows the Brier verdict, but the swingy accuracy % is held back until
    # the headline floor (≥10) — below it, the ✓/✗ tally carries the record.
    live = [dict(_r(0.8, "hit"), kind="stage_advance") for _ in range(4)]
    tag = fc.calibration_tagline(fc.calibration_headline(live))
    assert "% accurate across" not in tag and "Brier" in tag and "Headline accuracy holds" in tag


def test_open_forecast_table_rows():
    preds = [
        {"kind": "stage_advance", "claim": "X advances", "confidence": 0.6,
         "horizon": "short", "resolve_by": "2026-09-10"},
        {"kind": "price_move", "claim": "Y up", "confidence": 0.5,
         "horizon": "short", "resolve_by": "2026-09-10"},
        {"kind": "manual", "claim": "Z holds", "confidence": 0.75,
         "horizon": "long", "resolve_by": "2027-01-01"},
    ]
    rows = fc.open_forecast_table(preds)
    assert [r["Conf %"] for r in rows] == [75, 60, 50]          # sorted by confidence desc
    top = rows[0]
    assert top["Category"] == "Strategist (judgment)" and top["Type"] == "judgment"
    assert rows[1]["Type"] == "auto" and rows[1]["Forecast"] == "X advances"
    assert {"Category", "Forecast", "Conf %", "Horizon", "Resolve by", "Type"} == set(top)


def test_calibration_bins_and_chart():
    resolved = [_r(0.85, "hit"), _r(0.82, "miss"), _r(0.15, "miss"), _r(0.18, "miss")]
    bins = fc.calibration_bins(resolved, n_bins=5)
    top = next(b for b in bins if b["band"] == "80–100%")
    assert top["n"] == 2 and top["actual"] == 0.5          # 1 hit of 2
    low = next(b for b in bins if b["band"] == "0–20%")
    assert low["actual"] == 0.0
    assert fc.calibration_chart(bins) is not None
    assert fc.calibration_chart([]) is None


# ── threshold calibration (data-driven auto-template thresholds, pure) ────────
def test_threshold_for_target_rate_percentile_math():
    # 10 windows with values 1..10 @ target 0.6 → t=5: exactly 6/10 windows ≥ 5.
    assert fc.threshold_for_target_rate(list(range(1, 11)), target=0.6) == 5
    # target 0.5 over [1,2,3,4] → 3 (2/4 windows ≥ 3)
    assert fc.threshold_for_target_rate([1, 2, 3, 4], target=0.5) == 3
    # constant history → that constant; empty → None
    assert fc.threshold_for_target_rate([4, 4, 4, 4]) == 4
    assert fc.threshold_for_target_rate([]) is None


def test_deal_flow_calibration_from_known_distributions():
    days = [f"2026-05-{d:02d}" for d in range(24, 32)] + \
           [f"2026-06-{d:02d}" for d in range(1, 31)] + \
           [f"2026-07-{d:02d}" for d in range(1, 4)]
    cal = fc.deal_flow_calibration(
        {
            "Busy": days,                                   # a deal every day
            "Mid": [f"2026-06-{d:02d}" for d in range(1, 9)],   # 8 deals early June
            "Sparse": ["2026-07-01"],                       # one recent deal
        },
        as_of="2026-07-03", earliest="2026-05-24")          # → 11 rolling 30d windows
    # every 30d window holds 30 deals → p60=30, clamped to the cap
    assert cal["Busy"]["threshold"] == fc.DEAL_FLOW_THRESHOLD_CAP
    # window counts newest-first [5,6,7,8,8,8,8,8,8,8,8] → p60 = 8
    assert cal["Mid"]["threshold"] == 8
    assert cal["Mid"]["basis"] == "calibrated-p60 (trailing 11 × 30d windows)"
    # p60 of a mostly-zero history → clamped up to the old constant (the floor)
    assert cal["Sparse"]["threshold"] == fc.DEAL_FLOW_THRESHOLD


def test_deal_flow_calibration_thin_history_falls_back():
    # only 18 days of retained rows → 0 full 30d windows → old constant, marked
    cal = fc.deal_flow_calibration({"Chips": ["2026-07-01", "2026-07-02"]},
                                   as_of="2026-07-03", earliest="2026-06-15")
    assert cal["Chips"]["threshold"] == fc.DEAL_FLOW_THRESHOLD
    assert "thin history" in cal["Chips"]["basis"]
    # no history at all (earliest unknown) → same fallback
    cal2 = fc.deal_flow_calibration({"Chips": []}, as_of="2026-07-03", earliest=None)
    assert cal2["Chips"]["threshold"] == fc.DEAL_FLOW_THRESHOLD


def test_reactivity_calibration_from_known_moves():
    cal = fc.reactivity_calibration(
        {
            # 5.5% move in 9 of 11 windows, 3.0% in the other 2 → p60 = 5.5
            "Chips": [("2026-06-25", 5.5), ("2026-06-25", -1.0), ("2026-06-10", 3.0)],
            "Quiet": [("2026-06-25", 0.8)],   # sub-floor moves → clamped to the floor
        },
        as_of="2026-07-03", earliest="2026-05-24")
    assert cal["Chips"]["threshold_pct"] == 5.5
    assert cal["Chips"]["basis"] == "calibrated-p60 (trailing 11 × 30d windows)"
    assert cal["Quiet"]["threshold_pct"] == fc.REACTIVITY_THRESHOLD_PCT
    # thin history → old constant, marked
    thin = fc.reactivity_calibration({"Chips": [("2026-07-01", 9.0)]},
                                     as_of="2026-07-03", earliest="2026-06-20")
    assert thin["Chips"]["threshold_pct"] == fc.REACTIVITY_THRESHOLD_PCT
    assert "thin history" in thin["Chips"]["basis"]


def test_gen_deal_flow_locks_calibrated_threshold_into_params_and_claim():
    cal = {"Chips": {"threshold": 5, "basis": "calibrated-p60 (trailing 11 × 30d windows)"}}
    out = fc.gen_deal_flow({"Chips": 12, "Auto & EV": 3}, as_of="2026-07-03",
                           calibration=cal)
    by = {p["subject"]: p for p in out}
    assert by["Chips"]["params"]["threshold"] == 5
    assert by["Chips"]["params"]["threshold_basis"].startswith("calibrated-p60")
    assert "≥5 more material deals" in by["Chips"]["claim"]
    # sector without a calibration entry keeps the old constant, marked as such
    assert by["Auto & EV"]["params"]["threshold"] == 2
    assert by["Auto & EV"]["params"]["threshold_basis"] == "fixed default"
    # activity gate respects the calibrated threshold (4 recent deals < threshold 6)
    gated = fc.gen_deal_flow({"Energy": 4}, as_of="2026-07-03",
                             calibration={"Energy": {"threshold": 6, "basis": "x"}})
    assert gated == []


def test_gen_reactivity_locks_calibrated_threshold_into_params_and_claim():
    cal = {"Chips": {"threshold_pct": 4.5, "basis": "calibrated-p60 (trailing 11 × 30d windows)"}}
    out = fc.gen_reactivity({"Chips": 2}, as_of="2026-07-03", calibration=cal)
    assert out[0]["params"]["threshold_pct"] == 4.5
    assert out[0]["params"]["threshold_basis"].startswith("calibrated-p60")
    assert "≥4.5%" in out[0]["claim"]
    # resolution reads the LOCKED param: a 4.0% move misses a 4.5% bar, clears 2%
    assert fc.resolve_reactivity(out[0], [4.0]) is None
    old = fc.gen_reactivity({"Chips": 2}, as_of="2026-07-03")[0]     # uncalibrated
    assert old["params"]["threshold_pct"] == 2.0 and "≥2%" in old["claim"]
    assert fc.resolve_reactivity(old, [4.0])[0] == "hit"


def test_sector_deal_dates_and_reaction_moves_and_earliest():
    class _Tk:
        def __init__(self, sector): self.sector = sector
    tf = lambda name: {"Nvidia": _Tk("Chips")}.get(name)
    rows = [
        {"published_at": "2026-06-10T09:00:00", "business_impact": "material",
         "scope": "deal", "companies": ["Nvidia"], "tags": []},
        {"published_at": "2026-06-12", "business_impact": "low",       # not material
         "scope": "deal", "companies": ["Nvidia"], "tags": []},
        {"published_at": "2026-06-01", "business_impact": "material",  # not capital
         "scope": "sector", "companies": ["Nvidia"], "tags": []},
    ]
    assert fc.sector_deal_dates(rows, tf) == {"Chips": ["2026-06-10"]}
    assert fc.earliest_published(rows) == "2026-06-01"
    assert fc.earliest_published([]) is None
    moves = fc.sector_reaction_moves(
        [{"company": "Nvidia", "event_date": "2026-06-11", "pct": -3.2},
         {"company": "Unknown Co", "event_date": "2026-06-11", "pct": 9.9}], tf)
    assert moves == {"Chips": [("2026-06-11", -3.2)]}


# ── stage_advance_tech (anchor-grounded maturity transitions, pure) ───────────
_SSB = {"tech": "solid-state-batteries", "label": "Solid-state batteries",
        "stage_articles": 20, "stage_dist": {"emerging": 12, "growth": 8},
        "committed_stage": "emerging", "mixed": False}


def test_gen_stage_advance_tech_selects_boundary_techs_with_varied_confidence():
    placements = [
        dict(_SSB),                                                    # upside 0.40
        {"tech": "quantum-computing", "label": "Quantum computing",
         "stage_articles": 8, "stage_dist": {"emerging": 6, "growth": 2},
         "committed_stage": "emerging", "mixed": True},                # upside 0.25, contested
        {"tech": "critical-minerals", "label": "Critical minerals",
         "lifecycle_fit": False, "stage_articles": 30,
         "stage_dist": {"growth": 30}, "committed_stage": "growth"},   # not a technology
        {"tech": "glp-1", "label": "GLP-1", "stage_articles": 25,
         "stage_dist": {"emerging": 20, "growth": 5},
         "committed_stage": "growth", "mixed": False},                 # anchored above news → no upside
        {"tech": "gene-editing", "label": "Gene editing", "stage_articles": 3,
         "stage_dist": {"emerging": 1, "growth": 2}, "committed_stage": "emerging"},  # thin
        {"tech": "lfp-batteries", "label": "LFP", "stage_articles": 15,
         "stage_dist": {"mature": 10, "declining": 5}, "committed_stage": "mature"},  # no room
    ]
    out = fc.gen_stage_advance_tech(placements, as_of="2026-07-03")
    assert [p["subject"] for p in out] == ["solid-state-batteries", "quantum-computing"]
    ssb, qc = out
    assert ssb["kind"] == "stage_advance_tech"
    assert "from ‘emerging’ to ‘growth’" in ssb["claim"]
    assert ssb["params"] == {"dimension": "maturity", "from_stage": "emerging",
                             "from_index": 1, "to_stage": "growth", "to_index": 2,
                             "upside_share": 0.4, "label": "Solid-state batteries"}
    assert ssb["resolve_by"] == "2026-10-01"          # +90d — "within ~1 quarter"
    # evidence heuristic, not a constant: more upside + coverage → more confidence,
    # contested placement docked
    assert ssb["confidence"] == 0.59 and qc["confidence"] == 0.47
    assert "contested placement" in qc["basis"]


def test_gen_stage_advance_tech_caps_and_ranks_by_upside():
    placements = [
        {"tech": f"t{i}", "label": f"T{i}", "stage_articles": 12,
         "stage_dist": {"emerging": 12 - i, "growth": i},   # upside i/12
         "committed_stage": "emerging", "mixed": False}
        for i in range(4, 12)                               # 8 qualifying techs
    ]
    out = fc.gen_stage_advance_tech(placements, as_of="2026-07-03")
    assert len(out) == 6                                    # capped per run
    assert [p["subject"] for p in out] == ["t11", "t10", "t9", "t8", "t7", "t6"]


def test_gen_stage_advance_tech_fingerprint_stable_per_day():
    a = fc.gen_stage_advance_tech([dict(_SSB)], as_of="2026-07-03")[0]
    b = fc.gen_stage_advance_tech([dict(_SSB)], as_of="2026-07-03")[0]
    c = fc.gen_stage_advance_tech([dict(_SSB)], as_of="2026-07-04")[0]
    assert a["fingerprint"] == b["fingerprint"]             # idempotent same day
    assert a["fingerprint"] != c["fingerprint"]             # new cycle, new fp
    # independent of confidence/claim wording — same basis as every other kind
    assert a["fingerprint"] == fc._fp("stage_advance_tech|solid-state-batteries|2026-07-03")


def _sat_pred(**kw):
    p = {"subject": "ssb", "made_on": "2026-07-03", "resolve_by": "2026-10-01",
         "params": {"to_index": 2}}
    p.update(kw)
    return p


def _snap(as_of, stage, mixed=False, tech="ssb"):
    return {"technology": tech, "as_of": as_of, "maturity_stage": stage,
            "maturity_mixed": mixed}


def test_resolve_stage_advance_tech_hit_needs_confirmed_clean_advance():
    pred = _sat_pred()
    # two consecutive clean snapshots at the target → HIT (notes the confirming date)
    res = fc.resolve_stage_advance_tech(
        pred, [_snap("2026-07-20", "growth"), _snap("2026-07-21", "growth")])
    assert res and res[0] == "hit" and "2026-07-21" in res[1]
    # a LATER stage also counts ("target or later")
    res = fc.resolve_stage_advance_tech(
        pred, [_snap("2026-07-20", "dominant-design"), _snap("2026-07-21", "growth")])
    assert res and res[0] == "hit"
    # a single-snapshot flip is unconfirmed → stays open
    assert fc.resolve_stage_advance_tech(pred, [_snap("2026-07-20", "growth")]) is None
    # missing locked target → undecidable
    assert fc.resolve_stage_advance_tech({"subject": "ssb", "params": {}}, []) is None


def test_resolve_stage_advance_tech_suspect_moves_never_hit():
    pred = _sat_pred()
    # contested (mixed) snapshots never confirm
    assert fc.resolve_stage_advance_tech(
        pred, [_snap("2026-07-20", "growth", mixed=True),
               _snap("2026-07-21", "growth", mixed=True)]) is None
    # a contested reading RESETS the run — clean/contested/clean is not confirmed
    assert fc.resolve_stage_advance_tech(
        pred, [_snap("2026-07-20", "growth"), _snap("2026-07-21", "growth", mixed=True),
               _snap("2026-07-22", "growth")]) is None
    # a dip back below the target resets too
    assert fc.resolve_stage_advance_tech(
        pred, [_snap("2026-07-20", "growth"), _snap("2026-07-21", "emerging"),
               _snap("2026-07-22", "growth")]) is None
    # an unclassified gap is skipped, NOT a reset (coverage gap ≠ regression)
    res = fc.resolve_stage_advance_tech(
        pred, [_snap("2026-07-20", "growth"), _snap("2026-07-21", None),
               _snap("2026-07-22", "growth")])
    assert res and res[0] == "hit"


def test_resolve_stage_advance_tech_no_lookahead_or_window_leak():
    pred = _sat_pred()
    # a snapshot ON the made day never counts — strictly after made_on
    assert fc.resolve_stage_advance_tech(
        pred, [_snap("2026-07-03", "growth"), _snap("2026-07-04", "growth")]) is None
    # snapshots past resolve_by don't count
    assert fc.resolve_stage_advance_tech(
        pred, [_snap("2026-10-02", "growth"), _snap("2026-10-03", "growth")]) is None
    # other technologies' snapshots are ignored
    assert fc.resolve_stage_advance_tech(
        pred, [_snap("2026-07-20", "growth", tech="other"),
               _snap("2026-07-21", "growth", tech="other")]) is None


def test_stage_advance_tech_categorised_real_and_not_quarantined():
    assert fc.category_of("stage_advance_tech") == "Technology"
    assert not fc.is_quarantined({"kind": "stage_advance_tech"})
    resolved = [dict(_r(0.59, "hit"), kind="stage_advance_tech"),
                dict(_r(0.47, "miss"), kind="stage_advance_tech")]
    tr = fc.track_record(resolved)
    assert tr["resolved"] == 2 and tr["quarantined_resolved"] == 0   # counts in the headline
    cats = {c["category"]: c for c in fc.track_record_by_category(resolved)}
    assert cats["Technology"]["resolved"] == 2                        # lands naturally
    # and the learning loop covers it (recalibratable like the other real kinds)
    out = fc.apply_calibration([{"kind": "stage_advance_tech", "confidence": 0.5,
                                 "basis": "b"}],
                               {"stage_advance_tech": {"rate": 1.0, "n": 50}})
    assert out[0]["confidence"] == 0.7                                # shifted, ±0.2-capped


def test_resolution_evidence_stage_advance_tech_snapshots():
    ev = fc.resolution_evidence(
        {"kind": "stage_advance_tech", "subject": "ssb"},
        history=[_snap("2026-07-20", "growth"), _snap("2026-07-21", "growth", mixed=True),
                 _snap("2026-07-21", "growth", tech="other")])
    assert ev["snapshots_seen"] == [
        {"as_of": "2026-07-20", "stage": "growth", "mixed": False},
        {"as_of": "2026-07-21", "stage": "growth", "mixed": True},
    ]


# ── manual-resolution guard (locked-outcome discipline, pure) ─────────────────
def test_manual_resolution_guard_allows_only_open_manual():
    assert fc.manual_resolution_error(
        {"id": 1, "kind": "manual", "status": "open"}, "hit") is None


def test_manual_resolution_guard_rejects_auto_kinds():
    for kind in ("stage_advance", "stage_advance_tech", "posture_persist",
                 "deal_flow", "reactivity", "price_move"):
        err = fc.manual_resolution_error({"id": 1, "kind": kind, "status": "open"}, "hit")
        assert err and "auto-graded" in err


def test_manual_resolution_guard_rejects_already_resolved():
    err = fc.manual_resolution_error(
        {"id": 1, "kind": "manual", "status": "resolved", "outcome": "hit"}, "miss")
    assert err and "locked" in err


def test_manual_resolution_guard_rejects_bad_outcome_and_missing_row():
    assert "outcome must be" in fc.manual_resolution_error(
        {"id": 1, "kind": "manual", "status": "open"}, "won")
    assert "not found" in fc.manual_resolution_error(None, "hit")


# ── resolution basis: external (world-graded) vs internal (self-referential) ──
def test_resolution_basis_maps_every_kind():
    assert fc.resolution_basis("manual") == "external"
    for kind in ("stage_advance", "stage_advance_tech", "posture_persist",
                 "deal_flow", "reactivity"):
        assert fc.resolution_basis(kind) == "internal"
    assert fc.resolution_basis("price_move") == "quarantined"
    # unknown kinds land in the conservative bucket — never headline by accident
    assert fc.resolution_basis("future_new_kind") == "internal"


def test_records_by_basis_splits_and_reconciles():
    preds = [
        {"kind": "manual", "status": "resolved", "outcome": "hit", "confidence": 0.8},
        {"kind": "manual", "status": "open", "confidence": 0.6},
        {"kind": "stage_advance", "status": "resolved", "outcome": "miss", "confidence": 0.6},
        {"kind": "deal_flow", "status": "resolved", "outcome": "hit", "confidence": 0.7},
        {"kind": "price_move", "status": "resolved", "outcome": "hit", "confidence": 0.5},
    ]
    rb = fc.records_by_basis(preds)
    assert rb["external"]["resolved"] == 1 and rb["external"]["hits"] == 1
    assert rb["external"]["open"] == 1
    assert rb["internal"]["resolved"] == 2 and rb["internal"]["hits"] == 1
    # quarantined price call belongs to neither record — it stays in its own
    # category row (existing policy); external+internal+quarantined reconcile
    total_scored = rb["external"]["resolved"] + rb["internal"]["resolved"]
    assert total_scored == 3  # the price call is not double-counted anywhere


def test_track_record_by_category_carries_basis():
    preds = [
        {"kind": "manual", "status": "resolved", "outcome": "hit", "confidence": 0.8},
        {"kind": "stage_advance", "status": "open", "confidence": 0.6},
        {"kind": "price_move", "status": "resolved", "outcome": "miss", "confidence": 0.5},
    ]
    rows = {r["category"]: r["basis"] for r in fc.track_record_by_category(preds)}
    assert rows["Strategist (judgment)"] == "external"
    assert rows["Technology"] == "internal"
    assert rows["Price (low-signal)"] == "quarantined"
