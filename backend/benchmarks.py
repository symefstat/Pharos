"""
Seeded performance-proxy series per technology — so the S-curve can *measure*
something, not just position by classification.

A true S-curve (A1) is performance vs. cumulative effort/time. News volume isn't
performance, so we seed a small set of public learning-curve benchmarks (price,
efficiency, node size, throughput). These are **illustrative ballpark figures**
to demonstrate the measured curve — replace `series` with your own sourced data.

Keyed by technology key (see technologies.py). `lower_is_better=True` for cost /
node-size curves (the curve falls as the technology improves).
"""

from __future__ import annotations

BENCHMARKS: dict[str, dict] = {
    "lfp-batteries": {
        "metric": "Li-ion pack price",
        "unit": "$/kWh",
        "lower_is_better": True,
        "note": "BNEF-style battery learning curve (illustrative)",
        "series": [
            ("2013-01-01", 650), ("2016-01-01", 300), ("2019-01-01", 180),
            ("2021-01-01", 140), ("2023-01-01", 139), ("2024-01-01", 115),
        ],
    },
    "perovskite-solar": {
        "metric": "Cell efficiency",
        "unit": "%",
        "lower_is_better": False,
        "note": "NREL-style record perovskite cell efficiency (illustrative)",
        "series": [
            ("2012-01-01", 10.0), ("2015-01-01", 20.1), ("2018-01-01", 23.3),
            ("2021-01-01", 25.2), ("2024-01-01", 26.1),
        ],
    },
    "advanced-logic": {
        "metric": "Leading logic node",
        "unit": "nm",
        "lower_is_better": True,
        "note": "Flagship foundry process node (illustrative)",
        "series": [
            ("2014-01-01", 14), ("2017-01-01", 10), ("2018-01-01", 7),
            ("2020-01-01", 5), ("2022-01-01", 4), ("2025-01-01", 2),
        ],
    },
    "ai-accelerators": {
        "metric": "Flagship GPU throughput",
        "unit": "FP16 TFLOPS",
        "lower_is_better": False,
        "note": "Datacentre GPU peak throughput by generation (illustrative)",
        "series": [
            ("2016-01-01", 21), ("2017-01-01", 120), ("2020-01-01", 312),
            ("2022-01-01", 1000), ("2024-01-01", 2500),
        ],
    },
    "ai-datacenters": {
        "metric": "Data-centre efficiency (PUE)",
        "unit": "PUE",
        "lower_is_better": True,
        "note": "Hyperscale power usage effectiveness — lower is more efficient (illustrative)",
        "series": [
            ("2016-01-01", 1.58), ("2018-01-01", 1.50), ("2020-01-01", 1.46),
            ("2022-01-01", 1.42), ("2024-01-01", 1.39),
        ],
    },
    "green-hydrogen": {
        "metric": "Electrolyser capex",
        "unit": "$/kW",
        "lower_is_better": True,
        "note": "PEM electrolyser system cost (illustrative)",
        "series": [
            ("2015-01-01", 1400), ("2020-01-01", 1000), ("2023-01-01", 750),
            ("2025-01-01", 600),
        ],
    },
    "glp-1": {
        "metric": "Trial mean weight loss",
        "unit": "% body weight",
        "lower_is_better": False,
        "note": "Best-in-class GLP-1/GIP trial efficacy by generation (illustrative)",
        "series": [
            ("2017-01-01", 6.0), ("2021-01-01", 15.0), ("2023-01-01", 21.0),
            ("2025-01-01", 24.0),
        ],
    },
}

# Adoption/diffusion series — penetration over time, to quantify the chasm call
# (B2): higher = more mainstream adoption. Same shape as BENCHMARKS so they share
# the chart. Illustrative ballparks — replace with your own sourced data.
ADOPTION_BENCHMARKS: dict[str, dict] = {
    "ev-charging": {
        "metric": "EV share of new car sales",
        "unit": "% of new cars",
        "lower_is_better": False,
        "note": "Global plug-in EV share of new-car sales (illustrative)",
        "series": [
            ("2018-01-01", 2.1), ("2020-01-01", 4.2), ("2022-01-01", 13.0),
            ("2024-01-01", 18.0),
        ],
    },
    "generative-ai": {
        "metric": "Enterprises using generative AI",
        "unit": "% of firms",
        "lower_is_better": False,
        "note": "Share of enterprises with GenAI in production (illustrative)",
        "series": [
            ("2022-01-01", 18.0), ("2023-01-01", 55.0), ("2024-01-01", 72.0),
        ],
    },
    "grid-storage": {
        "metric": "Grid battery storage deployed",
        "unit": "GW cumulative",
        "lower_is_better": False,
        "note": "Cumulative grid-scale battery capacity (illustrative)",
        "series": [
            ("2018-01-01", 8.0), ("2020-01-01", 17.0), ("2022-01-01", 42.0),
            ("2024-01-01", 90.0),
        ],
    },
    "glp-1": {
        "metric": "US adults on a GLP-1",
        "unit": "% of adults",
        "lower_is_better": False,
        "note": "Estimated US adult GLP-1 usage (illustrative)",
        "series": [
            ("2021-01-01", 1.0), ("2023-01-01", 5.0), ("2024-01-01", 8.0),
        ],
    },
}
