# Phase 4 — L4 Aggregation / Rollup Integrity (offline)

Date: 2026-07-02 · Branch: `main` · All results below are offline (no Supabase/Toqan calls made; `.env` never read).

## 1. Verdict

**Offline: PASS with findings.** All 66 unit tests in the six L4 suites pass. The pure
reducers (dedup, day-bucketing, weight folds, momentum/SoV, alias normalization) behave as
documented and the eval recompute reuses the production counters, so a clean live diff is
achievable. However: **the live integrity check does not verify `by_company_breakdown`**
(the field every weighted view depends on), URL normalization can **over-merge distinct
query-string-keyed stories**, momentum's half-split is **off by one day**, and day
bucketing is **local-offset, not UTC**. None of these break the recompute-vs-stored diff
(build and recompute share the same code paths), but two operational effects can produce
**spurious non-zero drift** on a live run (§5, F6/F7) and must be accounted for before
declaring the acceptance target met.

```
./venv/bin/python -m pytest tests/test_rollup.py tests/test_aggregator.py tests/test_trends.py \
    tests/test_weights.py tests/test_entity_tracker.py tests/test_entities.py -q
66 passed, 1 warning in 0.13s        (warning = supabase/gotrue deprecation, not ours)
```

## 2. How the live check works (`eval_run.py --from-supabase`)

Read before proposing the live run (`eval_run.py:51–104`, `backend/eval/scoring.py:123–170`):

1. Reads **all 10 feed tables** (`home_news_articles`, `ai_energy_news_articles`,
   `disruptive_tech_articles`, `semiconductor_news_articles`, `geopolitics_trade_articles`,
   `climate_energy_articles`, `biotech_health_articles`, `software_security_articles`,
   `fintech_articles`, `defense_space_articles`) with `select("*") order published_at desc
   limit 1000` — deliberately the same order+cap as `RollupBuilder._rows`
   (`eval_run.py:37`, `analytics/rollup.py:134–146`).
2. Applies the **same** `dedup_by_feed` (first-feed-wins, FEEDS order) the builder uses —
   all feeds are read even under `--feed` so the dedup sees the full picture
   (`eval_run.py:84`).
3. Per feed: reads **all** stored `feed_daily_metrics` rows for that feed (no date filter,
   `eval_run.py:95–98`), recomputes per-day metrics from the deduped survivors via
   `recompute_rollup` (which imports the production counters `_count_scalar/_count_list/
   _count_companies` from `analytics/rollup.py`), and diffs day-by-day on 7 metrics:
   `total_articles, by_tag, by_company, by_country, by_sentiment, by_impact, by_scope`
   (`backend/eval/scoring.py:30–33`). A recomputed day absent from the rollup is flagged
   `missing_from_rollup`; days present only in the rollup (pruned from the feed) are
   correctly skipped as unverifiable.
4. Output: per-feed `{days_checked, clean, diffs}` in the scorecard (text or `--json`).

## 3. Test coverage map (invariant → tested?)

| Invariant | Tested? | Where / gap |
|---|---|---|
| Cross-feed dedup: first-feed-wins, syndicated story counted once | ✅ | test_rollup.py:12–30, 132–143 (incl. end-to-end entity-counted-once) |
| URL normalization collapses scheme/www/slash/query/fragment | ✅ | test_rollup.py:23, test_aggregator.py:13–24 |
| URL-less rows never collapsed together | ✅ | test_rollup.py:42–48 |
| Intra-feed duplicate dropped | ✅ | test_rollup.py:51–56 |
| **Query-only-distinct URLs stay distinct** | ❌ | **Fails — see F1** |
| Day bucketing skips undated/garbage `published_at` | ✅ | test_rollup.py:86–91 |
| **Day bucketing is timezone-correct (UTC)** | ❌ | **Not an invariant of the code — see F4** |
| Per-day marginals (tag/company/sentiment/impact) counted correctly | ✅ | test_rollup.py:72–83 |
| `by_company_breakdown` buckets by impact×tier, defaults handled | ✅ | test_rollup.py:98–129 |
| **Σ breakdown buckets per company == `by_company` count** | ❌ | untested consistency invariant between the two stored fields |
| Impact/tier weight lookup + defaults (missing/bogus → contextual/unknown) | ✅ | test_weights.py:23–58 |
| Legacy rows (no breakdown) weight neutrally at 1.0 | ✅ | test_weights.py:68–81, test_trends.py:165–170 |
| Empty inputs (build_rows / voice_share / momentum / headline / matrix) | ✅ | test_rollup.py:94, test_trends.py:98,133–134, test_entities.py:107 |
| **Weighted count rounding (`round()` on <0.5 weights → 0-count entries)** | ❌ | untested — an all-`none|unknown` entity (0.175/mention) displays as 0 |
| Momentum recent-vs-prior %, zero-prior, thin-base flag | ✅ | test_trends.py:47–77 |
| **Momentum halves are equal-length (flat volume → 0%)** | ❌ | **Fails — see F2** |
| Headline suppresses thin movers | ✅ | test_trends.py:102–117 |
| Voice share split/delta/Others/n_entities; weighted fold; tier tie-break | ✅ | test_trends.py:120–170 |
| Voice-share tie ordering at the `top` boundary | ❌ | untested (Counter insertion-order dependent; cosmetic) |
| Alias → canonical, case/whitespace, legal-suffix stripping, no-overstrip | ✅ | test_entities.py:6–53 (incl. Merck KGaA / Nu Holdings edge cases) |
| Co-mentions exclude self, normalize, weight by significance | ✅ | test_entities.py:56–67, test_entity_tracker.py:79–88 |
| Co-occurrence matrix symmetric, domain-coloured, singletons dropped | ✅ | test_entities.py:86–109 |
| Convergence seams, min_feeds, cross-cutting exclusion | ✅ | test_entity_tracker.py:16–76 |
| Picker/dossier agree when rollup empty (live fallback) | ✅ | test_entity_tracker.py:101–123 |
| **Eval recompute covers every metric the builder writes** | ❌ | **Fails — see F3 (`by_company_breakdown` unchecked)** |

## 4. Findings (bugs / gaps, with offline repros)

Repros run via `./venv/bin/python` with inline scripts (scratchpad); nothing written to the repo.

**F1 — `_normalize_url` over-merges stories distinguished only by query string.**
`analytics/aggregator.py:39–51` drops the entire query+fragment, so
`youtube.com/watch?v=AAAA` and `youtube.com/watch?v=BBBB` normalize to the identical key
`youtube.com/watch`; `dedup_by_feed` (`analytics/rollup.py:79–99`) then keeps only one.
Repro output: `equal: True`, `survivors: 1` (should be 2). Effect: silent **undercount**
for any publisher that keys articles on query params (YouTube, some CMSes, `?id=`,
`?p=`). Not a drift source (builder and eval share the code) — a data-fidelity bug.

**F2 — Momentum splits an inclusive window into uneven halves (off-by-one).**
`TrendsAggregator.rows` uses `gte(cutoff)` where cutoff = today − days
(`analytics/trends.py:43–48`), i.e. **days+1** calendar days; `momentum` sets
`mid = today − days//2` (`trends.py:114`), so for days=10 the recent half is 6 days and
the prior half 5. Repro: perfectly flat volume (1 article/day × 11 days) reports
`{'recent': 6, 'prior': 5, 'pct': 20.0, 'thin': False}` — a **+20% phantom momentum on
flat data**. Same skew propagates to `headline` (`trends.py:189–195`) and to
`voice_share` when callers derive `mid` the same way. Tests only ever place one row per
half (test_trends.py:47–77), so this is invisible to the suite.

**F3 — The live integrity check never verifies `by_company_breakdown`.**
`_ROLLUP_METRICS` (`backend/eval/scoring.py:30–33`) omits it and `recompute_rollup`
(`backend/eval/scoring.py:123–144`) doesn't recompute it, even though `build_rows` writes it
(`analytics/rollup.py:119`). Repro: corrupt a stored row's breakdown to
`{"Tesla": {"none|unknown": 999}}` → `rollup_integrity` returns `clean: True, diffs: []`.
This is exactly the drift the "recompute must mirror build_rows" comment warns about —
the metric list in scoring.py fell behind when the breakdown was added. **Every weighted
view (Share of Voice, weighted top companies, entity picker/dossier) reads this field,
and it is currently outside the acceptance check.** Suggested fix (not applied): add
`by_company_breakdown` to `_ROLLUP_METRICS` and `_count_company_breakdown` to
`recompute_rollup` — or have `recompute_rollup` call `build_rows` directly.

**F4 — Day bucketing is a raw string slice, not a UTC day.**
`build_rows` buckets on `str(published_at)[:10]` (`analytics/rollup.py:109`). Repro: the
same instant expressed as `2026-06-11T01:30:00+02:00` and `2026-06-10T23:30:00+00:00`
lands in **two different day buckets**. If feeds store non-UTC offsets, daily counts are
publisher-local-day, and momentum/SoV half-splits (which compare against
`date.today()`-derived ISO strings, server-local) inherit the ambiguity. Not a drift
source (recompute slices identically, `backend/eval/scoring.py:130`) — a semantic caveat to
document. Same pattern in `PulseAggregator._parse_date` cutoffs (`aggregator.py:30–36`,
local `date.today()` at `aggregator.py:82`).

**F5 — Alias-map edits create real (expected) drift until the next rollup run.**
`by_company` is normalized at **build time** (`rollup.py:54–61`), so editing
`analytics/entities.py`'s alias map makes the recompute (new map) diff against stored
rows (old map). Repro: a stored `{"Nu Holdings": 1}` row diffs against a recompute that
now normalizes `Nu Holdings Ltd → Nubank` (`clean: False, diff: by_company`). Self-heals
for in-window days on the next `RollupBuilder.run()`. Operational rule: **run the rollup
build immediately before the integrity check**, and treat post-alias-edit diffs on
still-in-feed days as expected.

**F6 — Boundary-day truncation can produce spurious diffs (live-run caveat).**
Both builder and eval read `limit 1000` newest-first. Once a feed table exceeds 1000
rows, the **oldest day inside the window is partially read**. The stored row for that day
was built earlier (when the day was fully inside the cap); the recompute now sees fewer
rows → spurious `total_articles`/marginal diffs on exactly one day per feed. Also
`order("published_at", desc)` has no tie-breaker (`rollup.py:139` vs the aggregator's
secondary `fetched_at` order at `aggregator.py:64–66`), so which rows make the cut at row
1000 is nondeterministic across queries. Interpretation rule for the live run: a diff
confined to each feed's **earliest recomputed day** is a read-window artifact, not
corruption; drift=0 should be asserted over the interior days.

**F7 — Rows ingested after the last rollup run diff as stale-today (live-run caveat).**
The stored rollup is only as fresh as the last `RollupBuilder.run()`; articles fetched
since then make today's recompute exceed today's stored counts. Same rule as F5: build
immediately before checking, or exclude the current day.

**Minor (no repro needed):** `by_impact` counts raw lowercased values and skips empties
(`rollup.py:36–42`) while the breakdown normalizes missing/bogus → `contextual`
(`rollup.py:71`), so `sum(by_impact) ≤ total_articles` and the two fields can disagree
per class — consistent build/recompute, but an untested cross-field invariant.
`voice_share` weighted mode can emit a floating-point-epsilon "Others" slice
(`trends.py:176–178`). `universe`/`co_mentions` `round()` can display 0 for real
low-weight entities (banker's rounding).

## 5. NEEDS APPROVAL — proposed live step (not executed)

**Command (from repo root):**
```
./venv/bin/python backend/eval_run.py --gold backend/eval/gold_labels.seed.jsonl --from-supabase --json
```
(optionally `--feed <key>` per feed; note all 10 feed tables are read regardless — only
the reported subset changes.)

- **Tables read (read-only, no writes):** the 10 feed tables listed in §2 at
  `limit 1000` each, plus `feed_daily_metrics` (full table, once per feed → 10 selects).
- **Expected volume:** ≤ 10 × 1000 feed rows + full rollup history (one row per
  feed-day; at 10 feeds × months of history, low thousands of small JSONB rows).
  ~20 PostgREST requests total, a few MB.
- **Cost:** **zero LLM calls** — pure select + pure-Python recompute. Needs only
  `SUPABASE_URL`/key from the environment (`db.get_supabase`); nothing else.
- **Sequencing for a meaningful drift=0:** run `RollupBuilder.run()` (or the scheduled
  job) immediately before, so F5/F7 staleness can't masquerade as corruption.
- **Acceptance interpretation:** drift = 0 on all interior days per feed. A diff **only**
  on a feed's earliest recomputed day (F6 boundary truncation) or on the current day (F7,
  if the rollup wasn't rebuilt first) is a known read-window artifact — record it, don't
  fail on it. Any other diff is a genuine integrity failure. Caveat even at drift = 0:
  `by_company_breakdown` is **not covered** by the check until F3 is fixed.

---

## Live integrity results (2026-07-02) — EXECUTED (read-only)

`eval_run.py --from-supabase` (gold: seed file, scoring section circular — see note):
**Rollup integrity CLEAN on all 10 feeds** (ev 14d, ai-energy 27d, disruption 29d,
chips 20d, geopolitics 21d, climate 27d, biotech 27d, software 19d, fintech 20d,
defense 28d — 232 feed-days, zero drift). **Acceptance target MET.**
Full output: `backend/eval/reports/live_scorecard_seed_20260702.txt`.

Note: the same run's lens-accuracy section (maturity 58.2% vs seed) is NOT an accuracy
measure — the seed labels are the lens's own guesses at seed time, so the 41.8%
disagreement measures **label drift/reconciliation churn since seeding**, plus 54/200
gold URLs no longer join (pruned past the read window). Both facts raise the urgency
of the human gold review (L3) and a rolling gold refresh.
