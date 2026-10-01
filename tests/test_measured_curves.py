"""Tests for the measured benchmark curves — the honesty contract, enforced.

Pure data checks (no network): every series is real-data-sized (>=6 points),
years strictly increase, every source has a URL, and values sit in sane ranges
per series (shares 0-100, prices positive and declining overall, capacity and
revenue increasing).
"""

from analytics.measured_curves import measured_curves

CURVES = {c["tech_key"]: c for c in measured_curves()}


class TestShape:
    def test_four_series(self):
        assert len(CURVES) == 4
        assert set(CURVES) == {
            "ev-charging", "perovskite-solar", "lfp-batteries", "ai-datacenters",
        }

    def test_tech_keys_exist_in_registry(self):
        from technologies import TECH_BY_KEY

        assert set(CURVES) <= set(TECH_BY_KEY)

    def test_required_fields(self):
        for c in CURVES.values():
            assert c["label"] and c["unit"] and c["direction_note"]
            for p in c["series"]:
                assert set(p) == {"year", "value"}
                assert isinstance(p["year"], int)
                assert isinstance(p["value"], (int, float))

    def test_at_least_six_real_points(self):
        for c in CURVES.values():
            assert len(c["series"]) >= 6, c["tech_key"]

    def test_years_strictly_monotonic(self):
        for c in CURVES.values():
            years = [p["year"] for p in c["series"]]
            assert years == sorted(years) and len(set(years)) == len(years)

    def test_sources_cited(self):
        for c in CURVES.values():
            src = c["source"]
            assert src["org"] and src["publication"]
            assert src["url"].startswith("https://")
            assert src["retrieved"] >= "2026-07"


class TestSaneRanges:
    def test_ev_share_is_a_percentage_and_rises(self):
        vals = [p["value"] for p in CURVES["ev-charging"]["series"]]
        assert all(0 <= v <= 100 for v in vals)
        assert vals == sorted(vals)          # diffusion never reversed
        assert vals[0] < 1 and vals[-1] >= 20  # foot of the S to takeoff

    def test_solar_capacity_strictly_increases(self):
        vals = [p["value"] for p in CURVES["perovskite-solar"]["series"]]
        assert all(v > 0 for v in vals)
        assert all(b > a for a, b in zip(vals, vals[1:]))  # cumulative

    def test_battery_price_positive_and_declining_overall(self):
        vals = [p["value"] for p in CURVES["lfp-batteries"]["series"]]
        assert all(v > 0 for v in vals)
        assert vals[-1] < vals[0] / 1.5      # learning curve, net decline
        assert max(vals) == vals[0]          # never above the 2017 start

    def test_battery_price_keeps_the_2022_uptick(self):
        # Honesty check: the real series is NOT monotonic — 2022 rose on
        # commodity spikes. A smoothed/invented series would hide this.
        by_year = {p["year"]: p["value"] for p in CURVES["lfp-batteries"]["series"]}
        assert by_year[2022] > by_year[2021]

    def test_ai_buildout_revenue_increases(self):
        vals = [p["value"] for p in CURVES["ai-datacenters"]["series"]]
        assert all(v > 0 for v in vals)
        assert all(b >= a for a, b in zip(vals, vals[1:]))
        assert vals[-1] > 50 * vals[0]       # the buildout inflection is in the data


class TestPurity:
    def test_accessor_returns_fresh_copies(self):
        a, b = measured_curves(), measured_curves()
        a[0]["series"][0]["value"] = -1
        a[0]["source"]["url"] = "clobbered"
        assert b[0]["series"][0]["value"] != -1
        assert b[0]["source"]["url"].startswith("https://")
