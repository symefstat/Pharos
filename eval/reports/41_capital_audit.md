# L6 Eval — Capital Tab vs Market Reality (live audit)

Date: 2026-07-02 (evening, after the user's refresh-all re-ran `financials_run.py` with today's fixes) · Follow-up to `eval/reports/06_financials.md` · Mode: Supabase READS only + ~35 approved yfinance calls + WebSearch for filed numbers. No writes to production.

**Stored snapshot audited**: 80 tickers in `company_financials`, all `as_of = 2026-07-02`; 10,641 price rows across 80 symbols in `stock_prices` (2025-12-12 → 2026-07-02); 2,076 feed rows (30d). Data was read via the app's own path (`backend/app/data.py: load_financials / load_prices / load_rows`) — exactly what `/api/capital` sees.

## Verdict summary

| # | Check | Verdict |
|---|---|---|
| 1 | FX purge (Samsung / ASML / TM) | ✅ **FX error is gone from the screen** — stored USD within 0.05% of live spot conversion (was +12.8% / −5.7% / +3.1%) |
| 2 | Fundamentals ±5%, 8 tickers | ✅ 8/8 pass; filed cross-checks 0.0–1.1% off; fiscal-anchor holds on real data |
| 3 | Exhibit recompute (rollup / share / 2×2) | ✅ exact match to independent recompute; the three "absurd-looking" points are all real-world true |
| 4 | Event-study sample (5 reactions) | ✅ 5/5 reproduce from fresh price history (baseline, window, direction) |
| 5 | Coverage gap | 39.7% coverage, 653 untracked entities; top-15 shortlist below (7 are private — no yfinance possible) |

---

## 1. FX purge check — the 06 report's headline defect is fixed in the data

`financials_run.py` now fetches live FX at write time (`finance/client.py: fx_rates_usd`, one batched request) and normalizes before upsert; the static map in `analytics/financials.py:367` is demoted to a logged fallback and was refreshed to 2026-07-02 values anyway. Tonight's refresh-all wrote through the new path. Stored vs fresh (live yfinance raw figure × live FX, 2026-07-02: KRW 0.0006497, EUR 1.14377, JPY 0.0062102, TWD 0.0313558):

| Ticker | Field | 06 report (stale-FX era) | Stored now | Live spot conversion | Δ now |
|---|---|---|---|---|---|
| 005930.KS | market cap | $1.371T (**+12.8%** ❌) | $1.2199T | $1.2202T | **−0.02%** ✅ |
| 005930.KS | revenue | $243.5B (+12.8% ❌) | $216.71B | $216.74B | −0.02% ✅ |
| ASML | revenue | $35.28B (**−5.7%** ❌) | $37.360B | $37.364B | −0.01% ✅ |
| ASML | market cap | (×1.08 era) | $681.93B | $681.93B (USD listing) | 0.0% ✅ |
| TM | revenue | $324.4B (+3.1% ⚠️ luck) | $314.60B | $314.76B | **−0.05%** ✅ |
| TM | market cap | — | $206.73B | $206.73B (USD listing) | 0.0% ✅ |

All three former offenders are now within 0.05% — far inside the ~2% acceptance band. The stored data is **CLEAN**; residual sub-0.1% drift is just intraday FX movement between the write and this audit. TSM (TWD reporter) also checked: revenue/R&D Δ +0.01%.

## 2. Fundamentals spot-check — 8 tickers, ±5% tolerance: 8/8 PASS

Stored (USD) vs live yfinance × live FX, plus filed numbers where checked:

| Ticker | Cap Δ | Rev Δ | R&D Δ | rd_intensity Δ | Filed cross-check |
|---|---|---|---|---|---|
| MSFT | −0.0% | 0.0% | 0.0% | 0.0% | FY25 10-K $281.7B / $32.49B (06 report) ✅ |
| NVDA | 0.0% | 0.0% | 0.0% | 0.0% | FY2026 10-K $215.9B / $18.497B (06 report) ✅ |
| AMD | 0.0% | 0.0% | 0.0% | 0.0% | **FY2025 10-K: revenue $34.6B, R&D $8.1B** — stored $34.639B / $8.091B ✅ ([AMD 10-K](https://www.sec.gov/Archives/edgar/data/0000002488/000000248826000018/amd-20251227.htm), [4Q25 release](https://ir.amd.com/news-events/press-releases/detail/1276/amd-reports-fourth-quarter-and-full-year-2025-financial-results)) |
| TSM | 0.0% | +0.01% | +0.01% | 0.0% | **2025 filed revenue NT$3,809.05B**; stored raw ≡ NT$3,809.2B, Δ 0.004% ✅ ([TSMC Dec-2025 revenue report](https://pr.tsmc.com/english/news/3278)) |
| 005930.KS | −0.02% | −0.02% | −0.02% | −0.0% | FY2025 ₩333.6T / ₩37.74T (06 report) ✅ |
| ASML | 0.0% | −0.01% | −0.01% | 0.0% | FY2025 €32.7B / €4.699B (06 report) ✅ |
| TM | −0.0% | −0.05% | — (None) | — (None) | Yahoo still carries no R&D row for TM → rd_intensity None (fail-soft; known coverage gap, unchanged) |
| PL (small-cap) | 0.0% | 0.0% | 0.0% | 0.0% | rd_intensity 34.7% — plausible for a growth small-cap; internally exact |
| MRNA (bonus) | — | **−1.1%** vs filed | **0.0%** vs filed | — | **FY2025 10-K: revenue $1,944M, R&D $3,132M** — stored $1,922M / $3,132M; the 163% intensity is REAL, see §3 ([Moderna 4Q25 results](https://www.accessnewswire.com/newsroom/en/healthcare-and-pharmaceutical/moderna-reports-fourth-quarter-and-fiscal-year-2025-financial-results-1137508), [10-K](https://www.sec.gov/Archives/edgar/data/0001682852/000168285226000033/mrna-20251231.htm)) |

**Fiscal-anchor fix on real data**: the new `_anchor_column`/`_at` path (`finance/client.py:36-84`) anchored every statement field to the revenue period for all tickers fetched; stored `rd_intensity == rd_expense / revenue` **exactly (80/80 rows)**, and the numerator/denominator provably share a fiscal column on the 8 live fetches. The 06 report's §3.2 period-mixing bug can no longer fire silently: a field null in the anchor period now returns None with a warning instead of reaching into FY(N−1). 18 companies have no R&D line → None, never 0 ✅.

## 3. Exhibit-logic recompute — app outputs ≡ independent recompute

Called `fa.landscape_points / sector_rollup / market_cap_share / capital_kpis` on the fetched stored rows (same functions `backend/app/capital.py:66-73` calls) and diffed against an independent recomputation (own median/share math):

- **Sector rollup** (8 sectors): company counts, total caps, median intensity/multiple/R&D — **all MATCH** to rounding. Big Tech $16.63T, Chips $15.63T, Biotech $3.54T, Software $2.26T, Auto & EV $2.26T, Fintech $1.76T, Defense $1.15T, Energy $0.63T. Total tracked cap $43.848T (= KPI tile).
- **market_cap_share**: shares 37.9 / 35.6 / 8.1 / 5.2 / 5.1 / 4.0 / 2.6 / 1.4 — all match; sum 99.9% (rounding). 30d deltas (Chips −2.1pp, Biotech +1.4pp) consistent with the price-weighted approximation.
- **2×2** (80 points, 0 dropped; median crosshairs x=19.25%, y=6.35×): quadrant census 26 premium+spend / 14 premium-without-spend / 14 spend-without-premium / 26 harvest.

**Quadrant sanity, 5 judged (all sensible):**
1. **Nvidia** in "premium without the spend" (x=11.4%, y=21.9×) — correct per the metric: fabless + capex-light, R&D 8.6% of a now-enormous revenue base; genuinely below the tracked-universe intensity median. The label reads counterintuitively for the world's biggest R&D machine in absolute $ — a caption nit, not a data error.
2. **Visa** (3.7%, 17.2×) — textbook: payment network, minimal R&D/capex, premium multiple. ✅
3. **Palantir** (13.2%, 69.3×) — sensible: software with modest R&D ratio and an extreme multiple; the 69× is real (cap $310B / rev $4.48B, both verified). ✅
4. **Apple** (11.4%, 10.9×) — sensible: outsourced manufacturing keeps capex+R&D ratio low. ✅
5. **Broadcom** (18.2%, 26.8×) — directionally fine but sits 1.05pp below the median split: quadrant membership is knife-edge; a one-company change to the universe could flip it. Cosmetic sensitivity, not an error.

**Absurdity scan — every outlier checked out as real, none are fiscal-mixing artifacts:**
- **Moderna rd_intensity 163% / intensity 173.5%**: matches the filed FY2025 10-K ($3,132M R&D over $1,944M revenue = 161% filed; Yahoo's "Total Revenue" $1,922M is −1.1% vs Moderna's $1,944M "total revenue" line). Same-period figures — real, not an artifact.
- **Oracle intensity 97.9%**: capex $55.66B on revenue $67.36B (FY2026, OCI buildout) — real.
- **Micron cap $1.102T**: world-confirmed — Micron crossed $1T in late May 2026 and is ~$1.1T in July 2026 ([CNBC](https://www.cnbc.com/2026/05/26/micron-stock-trillion-market-cap.html), [companiesmarketcap](https://companiesmarketcap.com/micron-technology/marketcap/)). Implied share count from stored cap ÷ stored close = 1.13B ✓.
- Implied-share cross-check also passes for PLTR (2.40B), ORCL (2.88B), INTC (5.03B — post the 2025 govt/SoftBank issuances), RKLB (0.62B), Samsung (~6.6B incl. prefs).
- One economics caveat (not a bug): multiples divide **today's** cap by **last-fiscal-year** revenue, so fast growers (RKLB 104×) look richer than a forward multiple would show. Consistent with the chart's own axis label.

**KPIs** (recomputed from full rows, identical to app): 359 typed deals (220 commitment : 139 option), top R&D = Moderna 163%, biggest reaction = Rocket Lab +18.4%, divergence 42 shrugged / 178 priced = 23.6%.

## 4. Event-study sample — 5/5 reproduce from fresh price history

Fresh 6-month yfinance download (independent of `stock_prices`), baseline/window/threshold recomputed from scratch:

| Event (stored) | Stored read | Fresh recompute | Match |
|---|---|---|---|
| RKLB · Iridium $8B acquisition · ev 06-29 | base 06-26 → post 07-01, **+18.4% up** | 84.54 → 100.07, +18.4%, baseline verified last close strictly before | ✅ |
| 005930.KS · ₩800T chip-cluster pledge · ev 07-01 | base 06-30 → post 07-02, **−14.4% down** | 334,000 → 286,000, −14.4%; window truncated to 2 trading days (honest) | ✅ |
| QCOM · Modular $3.9B · ev 06-24 | base 06-23 → post 06-26, **−7.2% down** | 204.13 → 189.39, −7.2% | ✅ |
| ABBV · Apogee $10.7B · ev Mon 06-22 | base **06-18** → post 06-24, **+8.5% up** | 216.49 → 234.89, +8.5%; base is Thu 06-18 because Fri 06-19 was the Juneteenth market holiday — no close skipped between baseline and event | ✅ |
| TM · Lexus LF-ZC cancellation · ev 07-02 (today) | base 07-01 → post 07-02, **+2.9% up** | 169.66 → 174.59, +2.9%; only 1 forward trading day yet — known nit: sub-window shares the full ±2% threshold | ✅ |

Baseline is strictly-before in all five (holiday and weekend gaps handled), the ≥2% direction call agrees, and stored `stock_prices` closes match Yahoo's current adjusted series.

## 5. Coverage gap — registry-expansion shortlist

From tonight's 30-day rows: **2,142 company mentions, 39.7% tracked** (851 tracked / 1,291 untracked; 653 distinct untracked entities — the app's "~621" figure is the same read a few hours earlier). Top-15 most-mentioned untracked, ranked:

| # | Company | Mentions | Status / yfinance symbol |
|---|---|---|---|
| 1 | SpaceX | 40 | **private** — no data possible |
| 2 | Anthropic | 32 | **private** |
| 3 | Circle | 22 | **public — CRCL (NYSE)** ← highest-value add |
| 4 | OpenAI | 20 | **private** |
| 5 | Tether | 18 | **private** |
| 6 | Anduril | 17 | **private** |
| 7 | Klarna | 14 | **public — KLAR (NYSE)** |
| 8 | RWE | 11 | **public — RWE.DE** (or RWEOY ADR; adds EUR reporter) |
| 9 | Binance | 11 | **private** |
| 10 | Databricks | 11 | **private** |
| 11 | Stripe | 10 | **private** |
| 12 | BlackRock | 10 | **public — BLK (NYSE)** |
| 13 | BMW | 9 | **public — BMW.DE** (or BMWYY ADR) |
| 14 | XPeng | 9 | **public — XPEV (NYSE ADR)** |
| 15 | General Atomics | 9 | **private** |

Next tier (8-9 mentions): Intellia Therapeutics (**NTLA** ✓ public), Hyundai (**005380.KS** ✓), Shield AI (private), Life Biosciences (private), Insilico Medicine (HK-listed 2025 — verify symbol before adding). Adding the 7 public names above (~93 mentions) would lift coverage ~39.7% → ~44%; the private giants (SpaceX/Anthropic/OpenAI/Anduril, 109 mentions) are the structural ceiling — correctly excluded per `tickers.py`'s "no fabricated figures" rule.

## Bottom line

The 06 report's one live-verified defect — stale static FX inflating Samsung +12.8% and skewing every non-USD USD figure — **is gone from the screen**: tonight's refresh wrote live-FX-normalized values (≤0.05% from spot) and the fiscal-anchor fix demonstrably prevents period mixing (80/80 internal consistency; None-not-zero preserved for the 18 no-R&D filers). Exhibits recompute exactly; every "absurd" number survived contact with filings and the market (Moderna 163%, Oracle 98%, Micron $1.1T all true). Remaining known gaps, all cosmetic or upstream: TM has no R&D row at Yahoo (drops from the 2×2), trailing-revenue multiples flatter fast growers, sub-window reactions share the full threshold, and coverage sits at ~40% with a clear 7-name public shortlist to widen it.
