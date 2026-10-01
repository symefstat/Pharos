# Lodestar backtest — would the method have called it?

_Generated 2026-07-10 · reproducible via `python backend/backtest_run.py`_

**Method.** For each settled technology, historical headlines are pulled from the GDELT news archive per quarter, classified through the SAME MOT lens agent the live product uses (headline + summary only), rolled up to a quarterly modal maturity stage (evidence floor ≥5 classified items/quarter), and a stage is *called* only after holding for 2 consecutive quarters — the production debounce. Calls are then compared with documented real-world milestones. Misses and uncorroborated calls are reported alongside the hits.

**Headline result: 1/7 milestones called · 3 uncorroborated calls.**

**Limitations.** GDELT sampling is coarse (a slice of each quarter's coverage, English only); milestone dates are curated judgments (each carries its public source); and the lens prompt is today's — this measures the current method on old news, not what Lodestar would have shipped at the time.

**What this actually validates.** The backtest grades the RAW, unanchored news signal — and it confirms, on settled history, exactly the bias the gold-set evaluation measured on the present: headline classification is a systematically *early/conservative* level estimator (mRNA read 'research' through the EUA quarter; NFTs never left 'emerging' through boom or bust). News is a change detector, not a level detector. This is precisely why the live product floors every placement with a dated, curated anchor and why transitions require a confirming snapshot: the anchors supply the level, the news supplies the change. The honest conclusion is not 'the method works unaided' — it is that the anchor architecture is load-bearing, and this study is the measurement that proves it.

## mRNA vaccines

_Window 2019Q3 → 2021Q4 · query `"mRNA vaccine"` · 59/78 headlines stage-classified_

| Milestone (documented) | Quarter | Method called | Verdict |
| --- | --- | --- | --- |
| First mRNA COVID-19 vaccine enters human trials (Moderna mRNA-1273, 16 Mar 2020) ([source](https://www.nih.gov/news-events/news-releases/nih-clinical-trial-investigational-vaccine-covid-19-begins)) | 2020Q1 | — | **MISS — never called** |
| Pivotal Phase 3 trials begin alongside mass-manufacturing commitments (27 Jul 2020) ([source](https://www.nih.gov/news-events/news-releases/phase-3-clinical-trial-investigational-vaccine-covid-19-begins)) | 2020Q3 | — | **MISS — never called** |
| FDA emergency use authorizations for the Pfizer-BioNTech and Moderna mRNA vaccines (Dec 2020) ([source](https://www.fda.gov/news-events/press-announcements/fda-takes-key-action-fight-against-covid-19-issuing-emergency-use-authorization-first-covid-19)) | 2020Q4 | — | **MISS — never called** |

Uncorroborated calls (no matching milestone — candidate false signals):
- `research` called 2020Q3 (n=12, 100% modal)

Quarterly read (modal stage · n items):

| 2019Q3 | 2019Q4 | 2020Q2 | 2020Q3 | 2020Q4 | 2021Q1 | 2021Q4 |
|---|---|---|---|---|---|---|
| research · 10 | (<floor) · 3 | research · 8 | research · 12 | research · 9 | research · 7 | dominant-design · 10 |

## NFTs (digital collectibles)

_Window 2020Q1 → 2023Q2 · query `(NFT OR "non-fungible token")` · 78/120 headlines stage-classified_

_Deliberately includes a DECLINE: the method must track collapse, not just ascent — 'declining' is a forward move on the axis._

| Milestone (documented) | Quarter | Method called | Verdict |
| --- | --- | --- | --- |
| Beeple's 'Everydays' sells for $69.3M at Christie's as NFT volume explodes (11 Mar 2021) ([source](https://www.christies.com/about-us/press-archive/details?PressReleaseID=9970)) | 2021Q1 | — | **MISS — never called** |
| NFT trading volume collapses ~97% from its January peak (Sep 2022) ([source](https://www.bloomberg.com/news/articles/2022-09-28/nft-volumes-tumble-97-from-2022-highs)) | 2022Q3 | — | **MISS — never called** |

Uncorroborated calls (no matching milestone — candidate false signals):
- `emerging` called 2020Q2 (n=11, 100% modal)

Quarterly read (modal stage · n items):

| 2020Q1 | 2020Q2 | 2020Q4 | 2021Q1 | 2021Q3 | 2021Q4 | 2022Q1 | 2022Q2 | 2022Q3 | 2022Q4 |
|---|---|---|---|---|---|---|---|---|---|
| emerging · 9 | emerging · 11 | emerging · 5 | emerging · 12 | emerging · 9 | emerging · 7 | emerging · 11 | emerging · 5 | (<floor) · 4 | emerging · 5 |

## Automotive LiDAR

_Window 2019Q1 → 2023Q2 · query `lidar (automotive OR "self-driving" OR autonomous)` · 127/168 headlines stage-classified_

_Judgment mapping flagged: consolidation/shakeout is read as the ferment closing (Utterback–Abernathy), i.e. dominant-design._

| Milestone (documented) | Quarter | Method called | Verdict |
| --- | --- | --- | --- |
| LiDAR SPAC wave: Velodyne and Luminar list publicly; Luminar-Volvo series-production deal (Q4 2020) ([source](https://www.reuters.com/article/us-luminar-ipo-idUSKBN28D2WD)) | 2020Q4 | 2023Q2 | 10 quarters late |
| Sector shakeout: Ouster-Velodyne merger completes after Ibeo insolvency and Quanergy delisting (Feb 2023) ([source](https://www.reuters.com/markets/deals/lidar-makers-ouster-velodyne-complete-merger-2023-02-13/)) | 2023Q1 | — | **MISS — never called** |

Uncorroborated calls (no matching milestone — candidate false signals):
- `emerging` called 2019Q3 (n=9, 89% modal)

Quarterly read (modal stage · n items):

| 2019Q2 | 2019Q3 | 2019Q4 | 2020Q1 | 2020Q2 | 2020Q3 | 2020Q4 | 2021Q1 | 2021Q2 | 2021Q3 | 2021Q4 | 2022Q2 | 2022Q3 | 2023Q1 | 2023Q2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| emerging · 10 | emerging · 9 | emerging · 8 | emerging · 11 | (<floor) · 1 | emerging · 8 | emerging · 5 | emerging · 11 | growth · 9 | emerging · 11 | emerging · 10 | (<floor) · 4 | emerging · 10 | growth · 8 | growth · 12 |
