# Measured curves — datapoint-by-datapoint audit trail

Companion to `analytics/measured_curves.py`. Every number in that module is
listed here with the source it was retrieved from, so each one can be checked.
All sources retrieved **2026-07-08**. No value is interpolated or estimated;
years without a published figure are simply absent from the series.

---

## 1. EV share of global new car sales (`ev-charging`)

**Source:** IEA, *Global EV Outlook* (2026 edition), series as processed and
republished by Our World in Data — "Share of new cars sold that are electric"
(battery-electric + plug-in hybrid, World).
URL: <https://ourworldindata.org/grapher/electric-car-sales-share> (CSV download, `World`)
Attribution per OWID metadata (<https://ourworldindata.org/grapher/electric-car-sales-share.metadata.json>):
"International Energy Agency. Global EV Outlook — processed by Our World in Data."

Cross-checks against IEA's own text: 2023 = 18% and 2024 sales "more than 20%"
(IEA GEO 2024/2025 executive summaries, <https://www.iea.org/reports/global-ev-outlook-2024/executive-summary>,
<https://www.iea.org/reports/global-ev-outlook-2025/executive-summary>); 2025 = 25%
(IEA GEO 2026, <https://www.iea.org/reports/global-ev-outlook-2026/trends-in-electric-cars>).

| Year | Value (%) | As retrieved | Note |
|------|-----------|--------------|------|
| 2012 | 0.2 | 0.17 | rounded to 0.1pp |
| 2013 | 0.3 | 0.29 | |
| 2014 | 0.4 | 0.44 | |
| 2015 | 0.7 | 0.68 | |
| 2016 | 1.0 | 0.95 | |
| 2017 | 1.4 | 1.4 | |
| 2018 | 2.4 | 2.4 | |
| 2019 | 2.7 | 2.7 | |
| 2020 | 4.4 | 4.4 | |
| 2021 | 9.3 | 9.3 | |
| 2022 | 15.0 | 15 | IEA GEO 2023 originally reported 14%; later editions revised to 15% |
| 2023 | 18.0 | 18 | matches IEA GEO 2024 exec summary ("18% of all cars sold") |
| 2024 | 21.0 | 21 | IEA GEO 2025 says "more than 20%" |
| 2025 | 25.0 | 25 | IEA GEO 2026: "25% of all new cars sold were electric" |

**Flag:** IEA revises early-year shares slightly between Outlook editions; the
series above is the GEO-2026-era revision as republished by OWID, not a splice
of contemporaneous press figures.

---

## 2. Solar PV cumulative installed capacity, world (`perovskite-solar` — closest registry key; this is the solar-domain benchmark)

**Source (2010–2024):** IRENA, *Renewable Energy Statistics*, as processed and
republished by Our World in Data — "Installed solar energy capacity" (World).
URL: <https://ourworldindata.org/grapher/installed-solar-pv-capacity> (CSV download, `World`)
Attribution per OWID metadata: "IRENA — Renewable Energy Statistics (2025) —
processed by Our World in Data." The indicator is IRENA's *total solar*
(on- and off-grid PV plus concentrated solar power; CSP is <0.5% of the total).

**Source (2025):** IRENA, *Renewable Capacity Statistics 2026* (H1 edition),
figure as reported by Solar Data Atlas: "World solar photovoltaic installed
capacity reached 2,383 GW at end-2025, with 510 GW added in a single year."
URL: <https://www.solardataatlas.com/en/data-solar-capacity-global>
(IRENA's own highlights PDF: <https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2026/Mar/IRENA_DAT_RE_capacity_highlights_2026.pdf>)

| Year | Value (GW) | As retrieved |
|------|------------|--------------|
| 2010 | 41.4 | 41.37 |
| 2011 | 72.4 | 72.42 |
| 2012 | 102.3 | 102.29 |
| 2013 | 139.0 | 139.00 |
| 2014 | 178.1 | 178.06 |
| 2015 | 225.7 | 225.72 |
| 2016 | 297.4 | 297.40 |
| 2017 | 391.5 | 391.50 |
| 2018 | 486.5 | 486.53 |
| 2019 | 588.7 | 588.69 |
| 2020 | 719.7 | 719.66 |
| 2021 | 863.0 | 862.99 |
| 2022 | 1056.4 | 1,056.37 |
| 2023 | 1413.5 | 1,413.47 |
| 2024 | 1866.3 | 1,866.31 |
| 2025 | 2383.0 | 2,383 (reported by Solar Data Atlas from IRENA RCS 2026) |

**Flags:** (a) the OWID/IRENA end-2024 figure (1,866 GW) differs slightly from
the Solar Data Atlas end-2024 figure (1,873 GW) — IRENA restates prior years
in each edition; we keep the OWID-retrieved value for 2010–2024 and splice only
2025 from the newer edition. (b) The IRENA 2026 highlights PDF itself was
fetched but could not be text-extracted in this environment, so the 2025
figure is cited "as reported by" Solar Data Atlas.

---

## 3. Lithium-ion battery pack price, volume-weighted average (`lfp-batteries`)

**Source:** BloombergNEF annual *Lithium-Ion Battery Price Survey*. Each point
is the headline all-sector volume-weighted average from **that year's** survey
press release (dollars nominal at time of survey; BNEF later restates history
in real dollars, which is why pre-2017 points are omitted rather than guessed).

| Year | $/kWh | Citation |
|------|-------|----------|
| 2017 | 209 | BNEF 2017 Battery Price Survey ("weighted average... $209/kWh"), <https://www.bnef.com/insights/17517>; drop confirmed as "18% since 2017" in the 2018 coverage, <https://www.bloomberg.com/news/videos/2018-12-21/bnef-brief-lithium-battery-prices-fall-18-percent-video> |
| 2018 | 176 | BloombergNEF, "A Behind the Scenes Take on Lithium-ion Battery Prices" ("fell 85% from 2010-18, reaching an average of $176/kWh"), <https://about.bnef.com/insights/clean-energy/behind-scenes-take-lithium-ion-battery-prices/> |
| 2019 | 156 | BNEF 2019 Battery Price Survey, reported by Utility Dive, <https://www.utilitydive.com/news/battery-prices-fall-nearly-50-in-3-years-spurring-more-electrification-b/568363/> |
| 2020 | 137 | BloombergNEF 2020 survey ("market average sits at $137/kWh"), <https://www.bnef.com/insights/25115>; also BNEF, <https://x.com/BloombergNEF/status/1339933494701682692> |
| 2021 | 132 | BloombergNEF, "Battery Pack Prices Fall to an Average of $132/kWh...", <https://about.bnef.com/insights/clean-energy/battery-pack-prices-fall-to-an-average-of-132-kwh-but-rising-commodity-prices-start-to-bite/> |
| 2022 | 151 | BNEF 2022 survey (first rise in survey history), reported by Energy-Storage.News, <https://www.energy-storage.news/lithium-battery-pack-prices-go-up-for-first-time-since-bloombergnef-began-annual-survey/> |
| 2023 | 139 | BloombergNEF, "Lithium-Ion Battery Pack Prices Hit Record Low of $139/kWh", <https://about.bnef.com/insights/clean-energy/lithium-ion-battery-pack-prices-hit-record-low-of-139-kwh/> |
| 2024 | 115 | BloombergNEF, "Lithium-Ion Battery Pack Prices See Largest Drop Since 2017, Falling to $115 per Kilowatt-Hour", <https://about.bnef.com/insights/commodities/lithium-ion-battery-pack-prices-see-largest-drop-since-2017-falling-to-115-per-kilowatt-hour-bloombergnef/> |
| 2025 | 108 | BloombergNEF, "Lithium-Ion Battery Pack Prices Fall to $108 Per Kilowatt-Hour, Despite Rising Metal Prices", <https://about.bnef.com/insights/clean-transport/lithium-ion-battery-pack-prices-fall-to-108-per-kilowatt-hour-despite-rising-metal-prices-bloombergnef/> |

**Flags:** (a) 2017's $209 and 2020's $137 headline figures sit on
BNEF-insights pages that are login-walled; the numbers themselves are the
widely-republished headline figures (see the Bloomberg video and Utility Dive
links). (b) Widely-circulated pre-2017 values (e.g. 2013 ≈ $668) could not be
matched to a fetchable primary/secondary source during this retrieval, so they
are **omitted**, not approximated.

---

## 4. Nvidia Data Center revenue by fiscal year (`ai-datacenters` — AI-buildout proxy)

**Source:** Nvidia quarterly earnings press releases and CFO commentary
(SEC Form 8-K exhibits). Year = Nvidia fiscal year, which ends late January of
that calendar year (FY2026 ended 2026-01-25). Values rounded to $0.1B.

| FY | $B | Citation (exact figure quoted) |
|----|-----|-------------------------------|
| 2019 | 2.9 | Q4 FY19 CFO commentary: Data Center full-year revenue $2,932M, up 52% — <https://www.sec.gov/Archives/edgar/data/0001045810/000104581019000007/q4fy19cfocommentary.htm> |
| 2020 | 3.0 | Q4 FY20 CFO commentary: "Data Center revenue was $2,983 million, up 2%" — <https://www.sec.gov/Archives/edgar/data/0001045810/000104581020000007/q4fy20cfocommentary.htm> |
| 2021 | 6.7 | Q4 FY21 press release: "$6.70 billion, up 124 percent" — <https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2021> |
| 2022 | 10.6 | Q4 FY22 press release: "Fiscal-year revenue rose 58 percent to a record $10.61 billion" — <https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2022> |
| 2023 | 15.0 | Q4 FY23 press release: "Fiscal-year revenue rose 41% to a record $15.01 billion" — <https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2023> |
| 2024 | 47.5 | Q4 FY24 press release: full-year Data Center revenue $47.5 billion, up 217% — <https://www.sec.gov/Archives/edgar/data/0001045810/000104581024000028/q4fy24pr.htm> |
| 2025 | 115.2 | Q4 FY25 press release: "Full-year revenue rose 142% to a record $115.2 billion" — <https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2025> |
| 2026 | 193.7 | Q4 FY26 press release: "Data Center full-year revenue rose 68% to a record $193.7 billion" — <https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2026> |

**Why not IEA data-centre TWh:** the IEA's *Energy and AI* report
(<https://www.iea.org/reports/energy-and-ai/executive-summary>) gives 415 TWh
for 2024 and a 485 TWh estimate for 2025, but no comparable published annual
history for 2019–2023 — two real points don't make a curve, so the revenue
proxy (8 audited points) was used instead, as the task brief allowed.

---

*Compiled 2026-07-08 for Lodestar Phase 2.4 (measured benchmark curves).*
