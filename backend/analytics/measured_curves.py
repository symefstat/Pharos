"""
Measured adoption / performance curves — real, citable series only.

The MOT Analyst page previously demonstrated its benchmark-curve panel with
illustrative seed data (`benchmarks.py` — explicitly ballpark). This module is
the replacement for the marquee curves: every datapoint below was retrieved
from a published source on the `retrieved` date and can be verified against
`docs/MEASURED_CURVES_SOURCES.md` at the repo root (one citation per datapoint).

The honesty contract:
  * No interpolation, no extrapolation, no invented values — a year is present
    only if a published figure exists for it (a series with 8 real points
    beats 15 approximate ones).
  * Each series carries its source (org, publication, url, retrieved) and a
    `direction_note` stating what movement means and any measurement caveats.
  * Where the canonical publisher's number was retrieved via a republisher
    (e.g. IEA figures processed by Our World in Data), the source says so.

Keys are the *closest* `technologies.py` registry key — these are domain-level
world benchmarks (EV adoption, solar build-out, battery learning curve, AI
data-centre buildout), attached to the tracked technology they contextualise.

Pure data + a pure accessor; no I/O, no caching, no network.
"""

from __future__ import annotations

_RETRIEVED = "2026-07-08"

_CURVES: list[dict] = [
    {
        "tech_key": "ev-charging",
        "label": "EV share of global new car sales",
        "unit": "% of new car sales",
        "series": [
            {"year": 2012, "value": 0.2},
            {"year": 2013, "value": 0.3},
            {"year": 2014, "value": 0.4},
            {"year": 2015, "value": 0.7},
            {"year": 2016, "value": 1.0},
            {"year": 2017, "value": 1.4},
            {"year": 2018, "value": 2.4},
            {"year": 2019, "value": 2.7},
            {"year": 2020, "value": 4.4},
            {"year": 2021, "value": 9.3},
            {"year": 2022, "value": 15.0},
            {"year": 2023, "value": 18.0},
            {"year": 2024, "value": 21.0},
            {"year": 2025, "value": 25.0},
        ],
        "source": {
            "org": "IEA",
            "publication": "Global EV Outlook (2026 edition; series processed by Our World in Data)",
            "url": "https://ourworldindata.org/grapher/electric-car-sales-share",
            "retrieved": _RETRIEVED,
        },
        "direction_note": (
            "Rising = diffusion. Battery-electric + plug-in hybrid share of new "
            "car sales, world. The textbook S-curve foot-to-takeoff: 14 years "
            "from 0.2% to 25%. IEA revises early-year shares slightly between "
            "Outlook editions (e.g. 2022 was reported as 14% in the 2023 "
            "edition, 15% after revision)."
        ),
    },
    {
        "tech_key": "perovskite-solar",
        "label": "Solar PV cumulative installed capacity (world)",
        "unit": "GW",
        "series": [
            {"year": 2010, "value": 41.4},
            {"year": 2011, "value": 72.4},
            {"year": 2012, "value": 102.3},
            {"year": 2013, "value": 139.0},
            {"year": 2014, "value": 178.1},
            {"year": 2015, "value": 225.7},
            {"year": 2016, "value": 297.4},
            {"year": 2017, "value": 391.5},
            {"year": 2018, "value": 486.5},
            {"year": 2019, "value": 588.7},
            {"year": 2020, "value": 719.7},
            {"year": 2021, "value": 863.0},
            {"year": 2022, "value": 1056.4},
            {"year": 2023, "value": 1413.5},
            {"year": 2024, "value": 1866.3},
            {"year": 2025, "value": 2383.0},
        ],
        "source": {
            "org": "IRENA",
            "publication": "Renewable Energy Statistics / Renewable Capacity Statistics 2026 "
                           "(2010-2024 processed by Our World in Data; 2025 as reported by Solar Data Atlas)",
            "url": "https://ourworldindata.org/grapher/installed-solar-pv-capacity",
            "retrieved": _RETRIEVED,
        },
        "direction_note": (
            "Rising = build-out. Cumulative grid-connected + off-grid solar "
            "capacity; IRENA's total-solar figure includes a small CSP share "
            "(<0.5%). ~58x in 15 years; the 2025 addition alone (~510 GW) "
            "exceeds everything installed up to 2018."
        ),
    },
    {
        "tech_key": "lfp-batteries",
        "label": "Lithium-ion battery pack price (volume-weighted average)",
        "unit": "$/kWh",
        "series": [
            {"year": 2017, "value": 209},
            {"year": 2018, "value": 176},
            {"year": 2019, "value": 156},
            {"year": 2020, "value": 137},
            {"year": 2021, "value": 132},
            {"year": 2022, "value": 151},
            {"year": 2023, "value": 139},
            {"year": 2024, "value": 115},
            {"year": 2025, "value": 108},
        ],
        "source": {
            "org": "BloombergNEF",
            "publication": "Annual Lithium-Ion Battery Price Survey (each point from that year's "
                           "BNEF survey release; dollars nominal at time of survey)",
            "url": "https://about.bnef.com/insights/clean-transport/lithium-ion-battery-pack-prices-fall-to-108-per-kilowatt-hour-despite-rising-metal-prices-bloombergnef/",
            "retrieved": _RETRIEVED,
        },
        "direction_note": (
            "Falling = learning curve (lower is better). All-sector pack "
            "average; the 2022 uptick is real — the first rise in the survey's "
            "history, on commodity-price spikes — before LFP-led declines "
            "resumed. Pre-2017 points omitted: BNEF restates early years in "
            "real dollars, so no stable public figure to cite."
        ),
    },
    {
        "tech_key": "ai-datacenters",
        "label": "Nvidia Data Center revenue (AI buildout proxy)",
        "unit": "$B per fiscal year",
        "series": [
            {"year": 2019, "value": 2.9},
            {"year": 2020, "value": 3.0},
            {"year": 2021, "value": 6.7},
            {"year": 2022, "value": 10.6},
            {"year": 2023, "value": 15.0},
            {"year": 2024, "value": 47.5},
            {"year": 2025, "value": 115.2},
            {"year": 2026, "value": 193.7},
        ],
        "source": {
            "org": "Nvidia",
            "publication": "Quarterly earnings releases / CFO commentary (SEC 8-K exhibits), "
                           "fiscal-year Data Center segment revenue",
            "url": "https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2026",
            "retrieved": _RETRIEVED,
        },
        "direction_note": (
            "Rising = AI infrastructure buildout. Year = Nvidia fiscal year "
            "(ends late January of that calendar year: FY2026 ended 2026-01-25). "
            "Revenue proxy chosen over IEA data-centre TWh because the IEA "
            "series is not published as a comparable annual history. ~66x in "
            "seven years, inflection at FY2024 (ChatGPT-era capex)."
        ),
    },
]


def measured_curves() -> list[dict]:
    """The measured benchmark curves — copies, so callers can't mutate the data."""
    return [
        {**c, "series": [dict(p) for p in c["series"]], "source": dict(c["source"])}
        for c in _CURVES
    ]
