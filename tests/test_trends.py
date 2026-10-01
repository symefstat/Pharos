"""Tests for TrendsAggregator's static reducers (pure)."""

from datetime import date, timedelta

import pytest

from analytics.trends import TrendsAggregator as TA
from analytics.weights import IMPACT_WEIGHTS as IW, TIER_WEIGHTS as TW


def test_daily_volume_maps_feed_label():
    rows = [{"feed": "ev", "metric_date": "2026-06-01", "total_articles": 5}]
    out = TA.daily_volume(rows)
    assert out == [{"date": "2026-06-01", "feed": "EV", "count": 5}]


def test_daily_sentiment_sums_across_feeds_per_day():
    rows = [
        {"metric_date": "2026-06-01", "by_sentiment": {"positive": 2, "negative": 1}},
        {"metric_date": "2026-06-01", "by_sentiment": {"positive": 3, "neutral": 4}},
        {"metric_date": "2026-06-02", "by_sentiment": {"negative": 5}},
    ]
    out = TA.daily_sentiment(rows)
    assert out[0] == {"date": "2026-06-01", "positive": 5, "negative": 1, "neutral": 4, "net": 4}
    assert out[1] == {"date": "2026-06-02", "positive": 0, "negative": 5, "neutral": 0, "net": -5}


def test_daily_sentiment_ignores_unknown_keys():
    rows = [{"metric_date": "2026-06-01", "by_sentiment": {"positive": 1, "bogus": 9}}]
    assert TA.daily_sentiment(rows)[0]["positive"] == 1


def test_sum_marginal_totals_and_ranks():
    rows = [
        {"by_company": {"Tesla": 3, "BYD": 1}},
        {"by_company": {"Tesla": 2, "Ford": 5}},
    ]
    out = TA.sum_marginal(rows, "by_company", top=2)
    assert out == [("Tesla", 5), ("Ford", 5)] or out == [("Ford", 5), ("Tesla", 5)]
    assert dict(TA.sum_marginal(rows, "by_company", top=10)) == {"Tesla": 5, "BYD": 1, "Ford": 5}


def test_sum_marginal_empty_field():
    assert TA.sum_marginal([{"x": 1}], "by_tag") == []


def test_momentum_recent_vs_prior():
    days = 10
    recent_day = date.today().isoformat()
    prior_day = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = [
        {"feed": "ev", "metric_date": recent_day, "total_articles": 20},
        {"feed": "ev", "metric_date": prior_day, "total_articles": 5},
    ]
    out = TA.momentum(rows, days)
    ev = next(r for r in out if r["feed"] == "EV")
    assert ev["recent"] == 20 and ev["prior"] == 5
    assert ev["pct"] == 300.0  # (20-5)/5 * 100
    assert ev["thin"] is False


def test_momentum_handles_zero_prior():
    # All-new coverage has no base to compute a % off — guarded to 0 and thin.
    rows = [{"feed": "ev", "metric_date": date.today().isoformat(), "total_articles": 4}]
    out = TA.momentum(rows, 10)
    assert out[0]["pct"] == 0.0 and out[0]["thin"] is True


def test_momentum_flags_thin_base():
    # A 0→1 swing has no trustworthy base → pct zeroed, thin=True.
    thin_rows = [{"feed": "ev", "metric_date": date.today().isoformat(), "total_articles": 1}]
    assert TA.momentum(thin_rows, 10)[0] == {"feed": "EV", "recent": 1, "prior": 0,
                                             "pct": 0.0, "thin": True}
    # A healthy base (prior half ≥ 5) is not thin.
    days = 10
    fat = [{"feed": "ev", "metric_date": date.today().isoformat(), "total_articles": 8},
           {"feed": "ev", "metric_date": (date.today() - timedelta(days=days - 1)).isoformat(),
            "total_articles": 5}]
    assert TA.momentum(fat, days)[0] == {"feed": "EV", "recent": 8, "prior": 5,
                                         "pct": 60.0, "thin": False}


def test_momentum_flat_volume_is_zero():
    # F2 regression: 1 article/day over the whole window must read 0% momentum
    # (the old inclusive-cutoff split compared 6 recent days vs 5 prior → +20%).
    days = 10
    rows = [{"feed": "ev", "metric_date": (date.today() - timedelta(days=i)).isoformat(),
             "total_articles": 1} for i in range(days)]
    out = TA.momentum(rows, days)[0]
    assert out["recent"] == 5 and out["prior"] == 5
    assert out["pct"] == 0.0 and out["thin"] is False


def test_momentum_half_boundary_off_by_one():
    # days=10 → recent = today-4..today, prior = today-9..today-5; today-10 is
    # outside the 10-day window and must be ignored even if a row sneaks in.
    days = 10
    today = date.today()

    def mk(i, n):
        return {"feed": "ev", "metric_date": (today - timedelta(days=i)).isoformat(),
                "total_articles": n}

    rows = [mk(4, 7), mk(5, 5), mk(9, 3), mk(10, 100)]
    out = TA.momentum(rows, days)[0]
    assert out["recent"] == 7      # today-4 lands in the recent half
    assert out["prior"] == 8       # today-5 + today-9; today-10 dropped


def test_momentum_odd_window_halves_stay_equal():
    # Odd window: the leftover oldest day is dropped so flat volume still reads 0%.
    days = 7
    rows = [{"feed": "ev", "metric_date": (date.today() - timedelta(days=i)).isoformat(),
             "total_articles": 2} for i in range(days)]
    out = TA.momentum(rows, days)[0]
    assert out["recent"] == 6 and out["prior"] == 6 and out["pct"] == 0.0


def test_momentum_small_base_guard():
    # Council finding: a 2→265 swing must NOT read "+13150%" — a prior-half base
    # below 5 articles yields pct 0 and thin=True, whatever the recent count.
    days = 10
    rows = [{"feed": "ev", "metric_date": date.today().isoformat(), "total_articles": 265},
            {"feed": "ev", "metric_date": (date.today() - timedelta(days=days - 1)).isoformat(),
             "total_articles": 2}]
    out = TA.momentum(rows, days)[0]
    assert out["recent"] == 265 and out["prior"] == 2
    assert out["pct"] == 0.0 and out["thin"] is True


def test_half_split_bounds():
    # Even window: halves cover the window exactly, days//2 each.
    lo, mid = TA.half_split(10)
    assert lo == (date.today() - timedelta(days=9)).isoformat()
    assert mid == (date.today() - timedelta(days=4)).isoformat()
    # Odd window: 3+3 days, the 7th (oldest) day falls before lo.
    lo7, mid7 = TA.half_split(7)
    assert lo7 == (date.today() - timedelta(days=5)).isoformat()
    assert mid7 == (date.today() - timedelta(days=2)).isoformat()


def test_headline_reports_momentum_and_sentiment():
    from datetime import date, timedelta
    days = 30
    recent = date.today().isoformat()
    prior = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = [
        {"feed": "ev", "metric_date": recent, "total_articles": 12, "by_sentiment": {"positive": 8, "negative": 2}},
        {"feed": "ev", "metric_date": prior, "total_articles": 5, "by_sentiment": {"positive": 1, "negative": 3}},
        {"feed": "chips", "metric_date": recent, "total_articles": 2, "by_sentiment": {"negative": 5}},
        {"feed": "chips", "metric_date": prior, "total_articles": 10, "by_sentiment": {"positive": 1}},
    ]
    txt = TA.headline(rows, days)
    assert "articles in range" in txt
    assert "Accelerating: **EV**" in txt      # ev 5->12
    assert "Cooling: **Chips**" in txt         # chips 10->2
    assert "Net sentiment" in txt


def test_headline_empty():
    assert TA.headline([], 30) == ""


def test_headline_overall_pct_guarded_on_small_base():
    # Council finding: a prior half of 2 articles must never headline "+13150%".
    # The aggregate guard now replaces the % claim with honest low-base wording
    # (raw counts) instead of the old misleading "+0%".
    days = 10
    recent = date.today().isoformat()
    prior = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = [{"feed": "ev", "metric_date": recent, "total_articles": 265, "by_sentiment": {}},
            {"feed": "ev", "metric_date": prior, "total_articles": 2, "by_sentiment": {}}]
    txt = TA.headline(rows, days)
    assert "13150" not in txt
    assert "low base" in txt
    assert "**265**" in txt and "**2**" in txt        # honest raw counts, not a %
    assert "vs the prior half" not in txt             # the % claim is gone entirely


def test_headline_aggregate_guard_fires_even_when_feeds_clear_per_feed_base():
    # The +12250% artifact: each feed clears the per-feed threshold (prior 10 ≥ 5),
    # but the window started mid-ramp — aggregate prior 20 vs recent 2470. The old
    # code headlined "+12250% vs the prior half"; now that aggregate claim is
    # suppressed for low-base wording. (Feeds are asymmetric so 12250 can only
    # come from the aggregate; the per-feed mover callouts keep their own gate.)
    days = 10
    recent = date.today().isoformat()
    prior = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = [
        {"feed": "ev", "metric_date": recent, "total_articles": 2035, "by_sentiment": {}},
        {"feed": "ev", "metric_date": prior, "total_articles": 10, "by_sentiment": {}},
        {"feed": "chips", "metric_date": recent, "total_articles": 435, "by_sentiment": {}},
        {"feed": "chips", "metric_date": prior, "total_articles": 10, "by_sentiment": {}},
    ]
    txt = TA.headline(rows, days)
    assert "12250" not in txt                            # the aggregate artifact is gone
    assert "vs the prior half" not in txt                # no aggregate % claim at all
    assert "low base" in txt and "**2470**" in txt and "**20**" in txt


def test_aggregate_momentum_boundaries():
    # Absolute floor: prior 30 with recent 120 sits exactly ON both limits
    # (30 ≥ 30 and 30 ≥ 0.25·120) → trusted, +300%.
    agg = TA.aggregate_momentum([{"recent": 120, "prior": 30}])
    assert agg == {"recent": 120, "prior": 30, "pct": 300.0, "thin": False}
    # One article under the floor → thin, % zeroed.
    agg = TA.aggregate_momentum([{"recent": 100, "prior": 29}])
    assert agg["thin"] is True and agg["pct"] == 0.0
    # Ratio guard: prior clears the floor but is <25% of the recent half → thin.
    agg = TA.aggregate_momentum([{"recent": 500, "prior": 100}])
    assert agg["thin"] is True and agg["pct"] == 0.0
    # Exactly 25% of the recent half → trusted again.
    agg = TA.aggregate_momentum([{"recent": 500, "prior": 125}])
    assert agg["thin"] is False and agg["pct"] == 300.0
    # Sums across feeds, not per-feed.
    agg = TA.aggregate_momentum([{"recent": 60, "prior": 20}, {"recent": 60, "prior": 20}])
    assert agg == {"recent": 120, "prior": 40, "pct": 200.0, "thin": False}


def test_headline_trusted_aggregate_still_reports_pct():
    # A healthy prior half (≥30 and ≥25% of recent) keeps the plain % headline.
    days = 10
    recent = date.today().isoformat()
    prior = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = [{"feed": "ev", "metric_date": recent, "total_articles": 60, "by_sentiment": {}},
            {"feed": "ev", "metric_date": prior, "total_articles": 40, "by_sentiment": {}}]
    txt = TA.headline(rows, days)
    assert "**+50%** vs the prior half" in txt
    assert "low base" not in txt


def test_headline_skips_thin_movers():
    # A near-dead feed (prior 1 → recent 3, base 1 < 5) is `thin`: the KPI/chart hide
    # it, so the headline must NOT crown it "Accelerating". A fat feed alongside
    # it should still surface.
    days = 30
    recent = date.today().isoformat()
    prior = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = [
        {"feed": "thinfeed", "metric_date": recent, "total_articles": 3},
        {"feed": "thinfeed", "metric_date": prior, "total_articles": 1},
        {"feed": "ev", "metric_date": recent, "total_articles": 12},
        {"feed": "ev", "metric_date": prior, "total_articles": 5},
    ]
    txt = TA.headline(rows, days)
    assert "Thinfeed" not in txt           # thin → suppressed from the headline
    assert "Accelerating: **EV**" in txt   # the healthy mover still surfaces


def test_voice_share_split_and_delta():
    rows = [
        {"metric_date": "2026-06-10", "by_company": {"Nvidia": 6, "TSMC": 2}},   # recent half
        {"metric_date": "2026-06-09", "by_company": {"Nvidia": 4, "Tesla": 8}},  # recent half
        {"metric_date": "2026-06-01", "by_company": {"Nvidia": 2, "TSMC": 8}},   # prior half
    ]
    sov = TA.voice_share(rows, mid="2026-06-05", top=2)
    assert sov["total"] == 20                                   # recent: 6+2+4+8
    by = {s["name"]: s for s in sov["slices"]}
    assert by["Nvidia"]["share"] == 50.0 and by["Tesla"]["share"] == 40.0
    assert by["Others"]["share"] == 10.0                        # TSMC (2) falls to the tail
    assert by["Nvidia"]["delta"] == 30.0                        # 50% now vs 20% prior (2/10)
    assert sov["n_entities"] == 3                               # Nvidia, TSMC, Tesla in the recent half
    assert TA.voice_share([], mid="2026-06-05")["slices"] == []
    assert TA.voice_share([], mid="2026-06-05")["n_entities"] == 0


def test_voice_share_weighted_folds_breakdown():
    # Tesla has more raw mentions but they're all 'none'; Nvidia's are 'material'.
    # Weighting flips the leader despite Nvidia's lower raw count.
    rows = [{
        "metric_date": "2026-06-10",
        "by_company_breakdown": {"Nvidia": {"material|unknown": 2},
                                 "Tesla": {"none|unknown": 4}},
    }]
    sov = TA.voice_share(rows, mid="2026-06-05", weighted=True)
    by = {s["name"]: s for s in sov["slices"]}
    nv = 2 * IW["material"] * TW["unknown"]
    te = 4 * IW["none"] * TW["unknown"]
    assert sov["total"] == pytest.approx(nv + te)
    assert by["Nvidia"]["share"] == round(100 * nv / (nv + te), 1)   # leader despite fewer mentions
    assert by["Nvidia"]["share"] > by["Tesla"]["share"]


def test_voice_share_weighted_source_tier_breaks_a_tie():
    # Equal raw mentions + impact; tier-1 source outranks an unknown-source rival.
    rows = [{
        "metric_date": "2026-06-10",
        "by_company_breakdown": {"Reuters Co": {"material|t1": 3},
                                 "Blog Co": {"material|unknown": 3}},
    }]
    by = {s["name"]: s for s in TA.voice_share(rows, mid="2026-06-05", weighted=True)["slices"]}
    assert by["Reuters Co"]["share"] > by["Blog Co"]["share"]


def test_voice_share_weighted_falls_back_to_raw_when_no_breakdown():
    # Old rows without a breakdown weight at a neutral 1.0 → identical to raw.
    rows = [{"metric_date": "2026-06-10", "by_company": {"Nvidia": 6, "Tesla": 4}}]
    w = {s["name"]: s["share"] for s in TA.voice_share(rows, mid="2026-06-05", weighted=True)["slices"]}
    raw = {s["name"]: s["share"] for s in TA.voice_share(rows, mid="2026-06-05", weighted=False)["slices"]}
    assert w == raw


def test_sum_marginal_weighted_company():
    rows = [{"by_company_breakdown": {"Nvidia": {"material|t1": 1},
                                      "Tesla": {"none|unknown": 4}}}]
    out = dict(TA.sum_marginal(rows, "by_company", weighted=True))
    assert out["Nvidia"] == pytest.approx(IW["material"] * TW["t1"])
    assert out["Tesla"] == pytest.approx(4 * IW["none"] * TW["unknown"])
    # Non-company fields ignore the weighted flag (raw counts).
    rows2 = [{"by_country": {"US": 2}}]
    assert TA.sum_marginal(rows2, "by_country", weighted=True) == [("US", 2)]
