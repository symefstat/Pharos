# L6 Eval — Financials & Capital Exhibits (offline)

Date: 2026-07-02 · Scope: `analytics/financials.py`, `finance/client.py`, `backend/app/capital.py`, `financials_run.py` (ingest), `net.py` · Mode: OFFLINE ONLY (no yfinance, no Supabase, no .env)

## 1. Test run

```
./venv/bin/python -m pytest tests/test_financials.py tests/test_finance_client.py tests/test_net.py -q
29 passed in 0.32s
```

Coverage highlights: event-study strictly-before baseline (`tests/test_financials.py:73-99`), R&D-intensity guards (:53), divergence split (:137-167), FX conversion (:198), retry semantics (`tests/test_net.py`, `tests/test_finance_client.py`).

## 2. Prior hardening (don't re-report)

Commit `555976e` ("finance hardening") changed only `finance/client.py` (+13/-4): wrapped the yfinance statement fetch in `net.retry` with backoff (`finance/client.py:40-48`), matching the batch-price path. Earlier commits (`b3de030`) added retries/timeouts and partial-success upserts in `financials_run.py:86-99`. The strictly-before event baseline and the listing-vs-reporting-currency split (`financial_currency`, `finance/client.py:82-99`) predate the hardening commit and are already fixed/tested — none of that is re-reported as open.

## 3. Audit findings

### 3.1 USD FX-normalization — correct architecture, static/stale rates

- **Where**: normalization happens **once, at write time** in `financials_run.py:54-72`: market cap converted by the **listing** currency (`:58`), revenue/R&D/capex/cash by the **reporting** currency `financial_currency` (`:57, :59-60, :69-70`), and the DB row is stamped `"currency": "USD"` (`:64`). Downstream calls to `market_cap_usd(f["market_cap"], f["currency"])` (`analytics/financials.py:246, 442, 535, 588, 594`) are therefore identity conversions. ADR mixing (e.g. TM: USD cap / JPY revenue) is handled. **Rule correct in code.**
- **Rate source**: hardcoded static map `_FX_TO_USD` of 10 currencies (`analytics/financials.py:360-361`). **No stale-rate handling** — no as_of, no refresh; rates look ~2024-vintage (EUR 1.08, JPY 0.0064). The comment says ratios "never use this", but post-ingest the valuation multiple = USD cap / USD revenue **does** embed the static rate whenever listing ≠ reporting currency, so a stale rate biases cross-currency multiples, USD totals, bubble sizes, and `market_cap_share`. (Caveat, not a correctness bug; comment at `:357-359` is slightly overstated.)
- **Edge cases**: unknown currency → `market_cap_usd` returns None → company silently dropped from landscape/rollup (any ticker reporting in a currency outside the 10-entry map, e.g. INR/SEK). Missing currency defaults to USD (`analytics/financials.py:370`) — wrong for a non-USD listing whose `fast_info.currency` comes back None.
- **Minor**: `financials_run.py:68` computes `rd_intensity(rev, rd)` from the *converted* values. FX cancels in the ratio, so an unknown reporting currency needlessly nulls an intensity that was computable from the raw figures.

### 3.2 R&D intensity — formula and guards correct; PERIOD-ALIGNMENT BUG (suspected)

- Formula `rd / revenue` with guards: non-numeric → None, `revenue <= 0` → None, negative R&D → None, zero R&D → 0.0 (`analytics/financials.py:30-39`). Correct.
- `investment_intensity` (`:384-397`): revenue ≤ 0 → None, missing R&D/capex treated as 0 but all-zero spend → None. Correct. `landscape_points`' `rev or 1.0` fallback (`:411`) is unreachable-in-practice because points without a positive-revenue intensity/multiple are filtered at `:408`.
- **BUG (confirmed offline)**: `finance/client.py:18-31` `_first()` picks the most recent **non-null** column *per row label independently* (`df.loc[name].dropna(); series.iloc[0]`). If the latest fiscal column has revenue but a NaN R&D row (common while Yahoo backfills a fresh filing), revenue comes from FY(N) and R&D from FY(N-1) — **numerator and denominator from different fiscal periods**. Same applies to capex vs revenue in `investment_intensity`.
  - Repro (offline, fake DataFrame): `/private/tmp/claude-501/-Users-symeon-efstathiou-Desktop-Simple-agent-testing-copy-5/29cf572c-4203-4880-90b8-122ee277d780/scratchpad/repro_period_alignment.py` — prints `rd_intensity computed = 15.0%` (FY2024 R&D 30 over FY2025 revenue 200) vs the true FY2024 intensity 30.0%. Off by 2× with no error surfaced.
  - Suggested direction (not applied): pick one anchor column (latest with revenue non-null) and read all statement rows from that column, or return `(value, period)` and align in the caller.

### 3.3 Event-study baseline — rule 100% correct in code

- `event_reaction` (`analytics/financials.py:62-108`): series sorted ascending (`:75-82`); baseline scan keeps the last index with `d < ev` — **strictly before** (`:87-91`); no baseline → None (`:92-93`).
- **Weekend/holiday gaps**: event on a non-trading day baselines to the last prior *trading* day (Fri close for a Sat/Sun/Mon-holiday event); test `:97-99` covers past-end events.
- **Same-day trades**: the announcement-day close can never be the baseline (strict `<`), so a same-day-absorbed jump is captured, not read as a shrug — regression-tested (`tests/test_financials.py:86-94`).
- **No look-ahead**: baseline close date ≤ event_date − 1 calendar day; for any market at UTC−x, a close on day D (≈ D 21:00 UTC for NYSE) always precedes a timestamp on day ≥ D+1 UTC, and markets east of UTC close even earlier relative to UTC. Worst case is a *conservative* baseline (one day earlier than strictly necessary for far-east exchanges), never leakage.
- **Timezone**: `_to_date` truncates `published_at` to its first 10 chars (`:53-59`) — the date in the stored timestamp's tz (UTC from Supabase); price dates are exchange-local from yfinance. Per above this cannot produce look-ahead, only occasional 1-day baseline conservatism. Acceptable.
- **Nits (not bugs)**: (a) `post_i` clamps to the series end (`:95`), so a recent event may measure over <window days — `trading_days` reports it honestly but `deal_reactions` applies the same ±2% threshold to 1-day and 3-day windows; (b) chart caption "~3 trading days after the deal" (`:719`) — the window is 3 trading days after the *baseline*, i.e. announcement day + 2.

### 3.4 Landscape 2×2 vs "market-shrugged" screen — same underlying numbers ✓

- Backend: `backend/app/capital.py` pulls `fins = data.financials()` (`:29`) and `prices = data.prices()` (`:30`) **once**; the 2×2 is `fa.landscape_points(fins, …)` (`:66`) and the shrugged screen is `reactions = fa.deal_reactions(rows, prices, …)` (`:83`) → `consensus_divergence(reactions)` (`:84`) — one copy of fundamentals/prices, no divergent snapshots.
- `consensus_divergence` (`analytics/financials.py:174-197`) splits on each reaction's **pre-computed** `direction` from `deal_reactions` (`:151`) — a single materiality threshold (2.0), matching `interpret_divergence(div, threshold=2.0)` at `capital.py:87`. `capital_kpis`/`company_scorecard` re-call `deal_reactions` with identical defaults (window=3, threshold=2.0) — recomputed but numerically identical (minor O(companies×rows) inefficiency, not a divergence).
- Streamlit parity: `Home.py:1884-1887, 2042-2044` uses the same `fins`/`prices`/reducers. Confirmed.

## 4. Open issues (ranked)

1. **Period misalignment in `_first`** (`finance/client.py:18-31`) — R&D/capex/cash can come from a different fiscal year than revenue; silently distorts rd_intensity, investment_intensity, and the 2×2 x-axis. Repro in scratchpad. **Suspected bug — report only, not fixed.**
2. **Static, undated FX map** (`analytics/financials.py:360-361`) — no staleness handling; biases USD caps and cross-currency multiples; currencies outside the 10-entry map silently drop companies.
3. Missing listing currency assumed USD (`analytics/financials.py:370`).
4. Cosmetic: sub-window reactions share the full-window threshold; "~3 days after the deal" label is baseline-relative.

## 5. Proposed live spot-check — NEEDS APPROVAL (not executed)

| Ticker | Why | Fields to check | Source of truth |
|---|---|---|---|
| MSFT | plain USD large-cap | revenue, R&D, capex, cash, market cap | FY10-K (SEC EDGAR) + cap vs Yahoo Finance page |
| TM | ADR: USD listing / JPY reporting | revenue & cash FX-normalization, valuation multiple sanity | Toyota FY filing (JPY) × current JPY rate |
| SSNLF or 005930.KS | KRW, tests the 0.00073 static rate | market_cap_usd vs live KRW/USD | Samsung IR + live FX |
| ASML | EUR reporter | revenue/R&D conversion, rd_intensity vs annual report | ASML 20-F |
| NVDA | R&D-heavy, recent filing | rd_intensity period alignment (bug #1 in the wild) | 10-K: same-FY R&D/revenue |

- Acceptance: each fundamental within **±5%** of source after FX; rd_intensity computed from same-period figures; event-study baselines re-verified on 2-3 real dated deals against a market calendar.
- Expected call volume: ~5 × (`Ticker.income_stmt` + `balance_sheet` + `cashflow` + `fast_info` + `info`) ≈ **25-30 yfinance requests**, plus 1 batched `yf.download` for the event-study check ≈ **~30 total**; retries could up to triple that under rate-limiting.
- **NEEDS APPROVAL** before any network call.

## 6. Verdict vs acceptance targets

- FX rule (listing vs reporting currency, normalize-at-write): **correct in code** (rate *values* static/stale — flagged).
- Event-study strictly-before baseline: **100% correct in code**, regression-tested, no look-ahead path found.
- Fundamentals ±5%: deferred to the approved live spot-check; bug #1 (period misalignment) is the main risk to passing it.

## Live spot-check results (2026-07-02)

Approved run executed via `eval/judges/finance_spotcheck.py` (uses the production
`finance.client.fundamentals` path + replicates `financials_run.py:57-68` USD
normalization; raw JSON in scratchpad `spotcheck_raw.json`). ~27 yfinance calls
(5 tickers × statements/fast_info/info + 2 batched downloads). Read-only — no
Supabase, no Toqan.

### Per-ticker: app value vs filed value (±5% target)

Fiscal periods picked by `_first()` shown per field. "Raw" = reporting-currency
value before the static-FX USD conversion.

| Ticker (period picked) | Field | App value | Filed value (source) | Δ % | Pass |
|---|---|---|---|---|---|
| MSFT (FY25, 2025-06-30) | revenue | $281.724B | $281.7B (FY25 Q4 8-K/10-K) | 0.0% | ✅ |
| | R&D | $32.488B | $32.49B (10-K) | 0.0% | ✅ |
| | rd_intensity | 11.53% | 11.53% same-FY | 0.0% | ✅ |
| | market cap | $2.85T | Yahoo-sourced (tautological) | — | sanity ✅ |
| TM (FY2026, 2026-03-31) | revenue (raw JPY) | ¥50,684.952B | ¥50.684T (Toyota FY2026 summary) | 0.0% | ✅ |
| | revenue (USD) | $324.4B (×0.0064) | $314.8B at live FX / $335.7B Toyota's own translation | +3.1% / −3.4% | ⚠️ passes only by FX luck |
| | R&D | **None** | ≈¥1.3T filed (record high per Toyota) | — | ⚠️ coverage gap: Yahoo has no TM R&D row → rd_intensity **None** (fail-soft, true ≈2.6%) |
| 005930.KS (FY2025, 2025-12-31) | revenue (raw KRW) | ₩333,605.9B | ₩333.6T (Samsung 4Q25 release) | 0.0% | ✅ |
| | R&D (raw KRW) | ₩37,740.4B | ₩37.7T (record, same release) | +0.1% | ✅ |
| | rd_intensity | 11.31% | same-FY, FX cancels | 0.0% | ✅ |
| | market cap (USD) | **$1.371T** (×0.00073) | $1.216T at live ₩1,544.6/$ | **+12.8%** | ❌ |
| | revenue (USD) | **$243.5B** | $216.0B at live FX | **+12.8%** | ❌ |
| ASML (FY2025, 2025-12-31) | revenue (raw EUR) | €32.667B | €32.7B (Q4-2025 release) | −0.1% | ✅ |
| | R&D (raw EUR) | €4.6988B | €4,699M (2025 AR) | 0.0% | ✅ |
| | rd_intensity | 14.38% | same-FY | 0.0% | ✅ |
| | revenue (USD) | **$35.28B** (×1.08) | $37.41B at live 1.1452 | **−5.7%** | ❌ (marginal) |
| NVDA (FY2026, 2026-01-31) | revenue | $215.938B | $215.9B (FY2026 10-K) | 0.0% | ✅ |
| | R&D | $18.497B | $18,497M (10-K) | 0.0% | ✅ |
| | rd_intensity | 8.57% | same-FY | 0.0% | ✅ |

Sources: [Microsoft FY25 Q4 press release](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q4/press-release-webcast), [Toyota FY2026 financial summary](https://global.toyota/pages/global_toyota/ir/financial-results/2026_4q_summary_en.pdf), [Samsung 4Q/FY2025 results](https://news.samsung.com/global/samsung-electronics-announces-fourth-quarter-and-fy-2025-results), [ASML 2025 results](https://www.asml.com/en/news/press-releases/2026/q4-2025-financial-results), [NVIDIA FY2026 10-K](https://www.sec.gov/Archives/edgar/data/0001045810/000104581026000021/nvda-20260125.htm).

### FX staleness (finding 3.1 confirmed live)

Live rates 2026-07-02 (yfinance `JPY=X`/`KRW=X`/`EURUSD=X`, cross-checked vs web):

| CCY | Static `_FX_TO_USD` | Live → USD | Static error |
|---|---|---|---|
| JPY | 0.0064 | 0.006210 (¥161.04/$) | **+3.1% high** |
| KRW | 0.00073 | 0.000647 (₩1,544.6/$) | **+12.8% high** |
| EUR | 1.08 | 1.1452 | **−5.7% low** |

The ~2024-vintage map is now ~2 years stale; KRW alone pushes every Samsung USD
figure (cap, revenue, bubble size, `market_cap_share`) ~13% high — well outside
the ±5% target. Ratios (rd_intensity, valuation multiple) are unaffected as
predicted (FX cancels; verified: `rd_intensity == rd_intensity_raw` on all tickers).

### Fiscal-year-mixing bug (§3.2) — did NOT fire today, 0/5

For all 5 tickers every field (revenue, R&D, capex, cash) came from the **same
latest column** (periods in table above), so live rd_intensity error from mixing
= 0 today. The vulnerable shape is real, though: TM's income statement contains
partial columns (2025-09-30, 2025-06-30) that are all-NaN and skipped per-row by
`dropna()` — exactly the structure that mixes periods the moment Yahoo backfills
one row of a fresh column before the others. Bug remains open (repro in §3.2);
today's data just doesn't trigger it.

### Event-study baseline on a real event

NVDA Q1-FY2027 results, announced **2026-05-20** (after close). From the
production `price_history_batch` series (120 closes, 2026-01-08 → 2026-07-01),
`event_reaction` picked baseline **2026-05-19** — strictly before the event,
verified to be the *last* close before it (no trading day skipped in between) —
post window 2026-05-22 (3 trading days), reaction **−2.4%**. Rule confirmed
correct on live data.

### Acceptance verdict vs ±5%

- **Reporting-currency fundamentals & rd_intensity: 5/5 PASS** — Yahoo mirrors
  the filings essentially exactly (most deltas 0.0%).
- **USD-normalized values: FAIL where listing/reporting FX ≠ USD** —
  005930.KS ❌ (+12.8%), ASML USD revenue ❌ (−5.7%, marginal), TM ⚠️ (+3.1%,
  inside tolerance only by luck). MSFT ✅, NVDA ✅ (no FX involved).
- **TM coverage gap**: Yahoo exposes no R&D line for TM → rd_intensity silently
  None (fail-soft, not wrong — but the 2×2 drops Toyota).
- Net: the pipeline is accurate at the source; the **static FX map is the one
  live-verified defect** (open issue #2 upgraded from "caveat" to measured
  ±6–13% bias). Fix direction: dated FX map or a free daily rate fetch with the
  same retry/degrade pattern as prices.
