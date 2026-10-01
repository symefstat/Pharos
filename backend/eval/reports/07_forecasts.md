# L7 — Forecasts / accountability engine (offline evaluation)

Date: 2026-07-02 · Mode: OFFLINE ONLY (no network, no Supabase, no LLM) ·
Scope: `analytics/forecasts.py`, `analytics/run_ledger.py`, `forecast_run.py`,
`forecast_reset.py`, `backend/app/forecasts.py`, `Home.py` (forecast surfaces),
`database/schema/predictions*.sql`, tests.

---

## 1. Test run

```
./venv/bin/python -m pytest tests/test_forecasts.py tests/test_forecast_reset.py tests/test_run_ledger.py -q
34 passed, 1 warning in 0.39s
```

(The warning is an unrelated `gotrue` deprecation from the supabase package import.)

Breakdown: `test_forecasts.py` 22 tests (generation, resolution, scoring,
calibration, evidence snapshots, quarantine breakout), `test_forecast_reset.py`
2 tests (premature-resolution predicate), `test_run_ledger.py` 10 tests
(pure record builder + fake-client write/degrade paths).

---

## 2. LOCKED-WHEN-MADE — every write path to `predictions`, traced

| # | Path | Fields written | Can it mutate prediction/horizon/threshold? |
|---|------|----------------|---------------------------------------------|
| 1 | `forecast_run.py:105` `generate()` INSERT | full row | No — insert-only; in-memory fingerprint dedup at `forecast_run.py:96-102`; DB `UNIQUE(fingerprint)` (`database/schema/predictions.sql`) makes re-runs idempotent |
| 2 | `forecast_run.py:207,214` `resolve()` UPDATE | `status, outcome, resolved_on, resolution_note, resolution_evidence` only (`forecast_run.py:201-205`) | No — never touches `claim/confidence/horizon/resolve_by/params` |
| 3 | `Home.py:2175` `_resolve_manual()` UPDATE | `status, outcome, resolved_on, resolution_note` | No prediction fields; **but no `kind=='manual'` / `status=='open'` guard in code** (UI only offers it for overdue manual calls) |
| 4 | `backend/app/forecasts.py:112-119` `POST /api/forecasts/resolve` UPDATE | same as #3 | No prediction fields; **same missing guard** — any `pred_id` (auto or already-resolved) can be graded/re-graded via the API; no evidence snapshot written |
| 5 | `forecast_reset.py:77` DELETE | row deletion | Deletion, not edit — dry-run by default, predicate-gated (`is_premature_resolution`, `forecast_reset.py:49-56`); `--all --apply` erases the whole ledger (manual CLI only) |

Key mechanisms:

- **Fingerprint** = `sha1(kind|subject|made-date)[:16]` (`forecasts.py:47-48`,
  `fp_basis` per generator, e.g. `forecasts.py:100,121,139,160,196,235`).
  Deliberately independent of confidence/claim text, so the learning loop
  (`apply_calibration`, `forecasts.py:549-572`) adjusts confidence **only on new
  candidates before insert** (`forecast_run.py:89`) and can never rewrite a
  logged forecast. `apply_calibration` returns new dicts, never mutates
  (pinned by `tests/test_forecasts.py:233-246`).
- `_mk()` (`forecasts.py:51-75`) freezes `made_on`, `resolve_by`
  (= made + `resolve_days`/horizon), confidence, and `params`
  (threshold/direction/tilt/from_index) at creation. Resolvers read thresholds
  back **from the stored `params`**, not from current config
  (`forecasts.py:279, 288, 321` — so changing a default later can't rewrite
  what an old forecast promised).

**Verdict:** prediction, horizon, and threshold are immutable across all code
paths. Enforcement is application-level only — there is **no DB trigger/RLS
guard** (RLS is explicitly disabled in `predictions.sql`), and the resolution
fields (`outcome`, `status`) are re-writable via paths #3/#4 by convention only.

## 3. OBJECTIVE RESOLUTION

All five auto resolvers are pure comparators over the system's own data — **no
model in the loop at resolution time**:

| Kind | Evidence | Comparator | Where |
|------|----------|------------|-------|
| `stage_advance` | `technology_stage_history` snapshots | stage index `>` locked `from_index`, window `(made_on, resolve_by]` | `forecasts.py:242-258` |
| `posture_persist` | recomputed sector tilt | equality vs locked tilt; HIT only at/after `resolve_by` (duration claim), flip = early MISS | `forecasts.py:261-275` |
| `deal_flow` | count of material capital deals strictly after `made_on` | `count >= locked threshold` | `forecasts.py:278-282`, count at `forecast_run.py:142-155` |
| `reactivity` | measured event-study \|moves\| since `made_on` | any `|pct| >= locked threshold_pct` | `forecasts.py:285-291` |
| `price_move` | `stock_prices` closes | point-to-point return vs locked `threshold` + `direction`; only decides once data reaches `resolve_by` | `forecasts.py:306-323` |

Backstop: still-open auto forecast past `resolve_by` → objective MISS
("criterion unmet by resolve-by date", `forecast_run.py:196-197`).

Subjectivity exists only in the `manual` (Strategist) kind, which is
**human-graded by design** (`backend/app/forecasts.py:104-123`, Home.py
`_resolve_manual`) and labeled "Strategist (judgment)" in every breakout.
Upstream, an LLM classifies rows as material/capital (feeds `deal_flow`/
`reactivity` counts), but that happens at ingestion — the same filter
(`_is_capital_row`) is applied symmetrically at generation and resolution.

## 4. NO LOOK-AHEAD / no same-day-HIT artifact

Code enforcement:

- `MIN_RESOLVE_DAYS = 7` (`forecasts.py:361`) applied to **all auto kinds, HIT
  and MISS**, at `forecast_run.py:172` — kills the day-0 "confirm the present"
  hit and same-day flip-miss.
- `resolve_stage_advance` skips history rows `d <= made_on` — strictly after
  (`forecasts.py:253`).
- `deals_since` skips deals `published_at <= made_on` (`forecast_run.py:149`);
  `sector_move_pcts` filters on the deal's **event date** `> made_on`
  (`forecast_run.py:136`, with an explicit comment on why not `base_date`).
- `resolve_posture_persist` cannot HIT before `resolve_by` (`forecasts.py:272-274`).
- `resolve_price_move` returns None until the series contains data through
  `resolve_by` (`forecasts.py:313-314`).
- `forecast_reset.py` retroactively purges historical artifacts:
  `is_premature_resolution` flags resolved auto rows with
  `resolved_on - made_on < 7` (dry-run by default).

Tests pinning it: `tests/test_forecasts.py:76-77` (advance recorded ON the made
day does not count), `:73-74` (advance outside window doesn't count), `:80-89`
(duration gating — still-tilted before resolve_by stays OPEN), `:98-102`
(`MIN_RESOLVE_DAYS == 7` + `elapsed_days`), `:144-145` (price stays open without
forward data); `tests/test_forecast_reset.py:12-29` (same-day auto resolution
flagged, manual/matured/open never flagged).

**0 look-ahead violations found in the resolution code.** Caveat (untested,
not look-ahead): the 7-day gate itself lives in the untested job
(`forecast_run.py:172`) — the tests pin the constant and helper, not the
enforcement point (see §7).

## 5. BRIER + CALIBRATION — hand-check (offline, exact match)

Formula in code (`forecasts.py:377-384`): mean of `(confidence − outcome)²`
with outcome ∈ {hit=1, partial=0.5, miss=0}. Bucketing
(`forecasts.py:387-405`): `bin = min(int(conf·n_bins), n_bins−1)`, actual =
mean outcome per band, predicted = band midpoint.

Hand-computed vs code output (`./venv/bin/python`, pure offline):

| Example | Hand | Code | Match |
|---|---|---|---|
| Brier [(0.8,hit),(0.6,miss),(0.5,partial)] | (0.04+0.36+0)/3 = **0.133** | 0.133 | ✓ (accuracy 0.5 = 0.5 ✓) |
| Brier [(0.75,hit),(0.55,miss),(0.4,miss),(0.5,hit)] | (0.0625+0.3025+0.16+0.25)/4 = **0.194** | 0.194 | ✓ |
| Brier 4 coin flips at 0.5 | **0.25** exactly | 0.25 | ✓ |
| Bins (n=5) for {0.85 hit, 0.82 miss, 0.15 miss, 0.18 miss, 0.5 hit, 0.55 miss, 0.75 hit} | 0–20%: 0.0 (n=2) · 40–60%: 0.5 (n=2) · 60–80%: 1.0 (n=1) · 80–100%: 0.5 (n=2) | identical | ✓ |

Float boundary check: `0.6·5 == 3.0`, `0.2·5 == 1.0`, `0.8·5 == 4.0` in IEEE
doubles — boundary confidences land in the upper band as intended; no float
drift bug. Notes (not bugs): (a) partial=0.5 makes this a 3-valued MSE, not a
strict binary Brier — documented in the docstring; (b) a boundary confidence
(0.6) is compared to the band midpoint 0.7 in the calibration chart, an
inherent ±10pp binning coarseness at n_bins=5.

**Acceptance: Brier/calibration hand-check exact — PASS.**

## 6. QUARANTINE of price-direction calls

Mechanisms in code:

- Category wall: `_CATEGORY["price_move"] = "Price (low-signal)"`
  (`forecasts.py:423-430`); `track_record_by_category` (`forecasts.py:437-449`)
  splits stats per category; surfaced in Home.py:2250-2259/2313 and
  `backend/app/forecasts.py:83`.
- Excluded from the learning loop: `_RECALIBRATABLE` omits `price_move` and
  `manual` (`forecasts.py:511`, `apply_calibration:553-558`).
- Confidence pinned at 0.50 (`forecasts.py:192`) — a resolved price call
  contributes exactly 0.25 to Brier regardless of outcome, so it cannot flatter
  the Brier; capped at top-8 movers (`forecasts.py:183-185`).
- Test coverage: `test_category_split_and_summary` (:152-164),
  `test_apply_calibration_skips_price_and_manual` (:233-246),
  `test_calibration_headline_states` (:269-276, "walled off, still visible"),
  `test_gen_reactivity_and_price_move` (:131, pinned 0.5).

**Finding — quarantine is NOT 100% by the strict definition.** The headline
`track_record` / `accuracy` / `brier` pool **all kinds including
`price_move`**: `calibration_headline` → `track_record(predictions)`
(`forecasts.py:589-600`), `backend/app/forecasts.py:29`, `Home.py:2216,2437`.
The UI copy claims "Price calls are quarantined so they can't flatter the
headline" (`Home.py:2465`), but they are only *broken out separately*, not
excluded from the headline numbers. Coin-flip price outcomes therefore dilute
headline accuracy toward 50% and Brier toward 0.25 (they can drag the headline
either way; the 0.5 pin means they can't inflate Brier-implied skill, and
top-8 capping bounds the dilution). Per-category breakouts themselves are
correct (verified by test + hand-read of the grouping code).

## 7. Order-independent termination + evidence snapshots — what the tests actually pin

- **Order-independent termination is NOT in `test_forecasts`** despite
  `EVAL_PLAN.md` listing it there. It is pinned in
  `tests/test_lens_reconcile.py:189-193` (lens layer): the fake `_unclassified`
  rotates fetch order every call to prove termination relies on the `attempted`
  set, not row order. For L7 itself, `resolve()` handles each prediction
  independently by id with per-key memoized deal counts (`forecast_run.py:139-155`),
  so it is order-independent by construction — but **no test pins that**.
- **Resolution-evidence snapshots**: `resolution_evidence()`
  (`forecasts.py:326-349`) captures per-kind what the resolver saw
  (stages_seen / tilt_now / deals_since / moves_pct / closes summary), pinned by
  `tests/test_forecasts.py:187-203` for all five kinds. Persisted with the
  verdict at `forecast_run.py:204`, computed from the **same variable** that fed
  the resolver (:175-195 comment + code). Rationale: `deal_flow`/`reactivity`
  count over feed rows that prune in 14-30d
  (`database/schema/predictions_evidence_column.sql`). Degrades gracefully if the
  column migration is pending (`forecast_run.py:208-214`) — i.e. evidence is
  best-effort, not schema-guaranteed. Manual grading writes no evidence.
- `run_ledger` tests pin: pure record shape, metrics dict copied (caller can't
  mutate the row), error coercion, missing-table signatures matched narrowly
  (constraint violations are NOT swallowed as "missing table"), and
  `record()` never raises (`tests/test_run_ledger.py`).

## 8. Gap summary — code vs convention vs untested

| Guarantee | Enforced by code | By convention only | Untested |
|---|---|---|---|
| Locked-when-made (claim/confidence/horizon/threshold) | ✓ all UPDATE paths touch resolution fields only; fingerprint UNIQUE; params read back from stored row | No DB-level immutability (no trigger; RLS disabled) | — |
| Outcome immutability after resolution | ✗ | `POST /api/forecasts/resolve` (`backend/app/forecasts.py:104-123`) and `Home.py:2175` accept **any** pred_id — no `kind=='manual'`/`status=='open'` guard; UI gating only | No test on either endpoint |
| Objective resolution | ✓ pure comparators, no LLM at resolve time | `manual` kind human-graded (by design, labeled) | Resolver units well tested |
| No look-ahead / no same-day HIT | ✓ 6 distinct guards (§4) | — | `forecast_run.py` `generate()`/`resolve()` have **zero tests** — the `MIN_RESOLVE_DAYS` gate (:172), overdue→miss backstop (:196), dedup (:91-102) are pinned only via their pure helpers |
| Brier + calibration math | ✓ exact (hand-verified) | — | — |
| Price quarantine | Partial: category wall + pinned 0.5 + recalibration exclusion + top-8 cap | **Headline accuracy/Brier still pool price calls** — UI copy overstates ("can't flatter the headline") | No test asserts headline excludes price (because it doesn't) |
| Evidence snapshots | ✓ content per kind | Persistence degrades if column missing; manual grades carry none | Degrade path untested |
| Order-independent termination | resolve() independent-by-id (by construction) | — | Not pinned for L7 (only for the lens layer) |
| Ledger reset honesty | Dry-run default, artifact predicate tested | `--all --apply` can erase the entire public record | CLI flow untested |

Recommended smallest fixes: (1) guard `/api/forecasts/resolve` with
`kind == 'manual' AND status == 'open'`; (2) either exclude `price_move` from
the headline `track_record` or soften the "can't flatter the headline" copy;
(3) add a `forecast_run.resolve()` unit test with a fake client pinning the
7-day gate and the overdue→miss backstop at the enforcement point.

## 9. PROPOSED live backtest — **NEEDS APPROVAL — NOT EXECUTED**

Read-only, zero LLM cost (`forecast_run` makes no agent calls; this plan makes
no writes at all):

1. **Dump the ledger**: `SELECT * FROM predictions` (paginated). Tables read:
   `predictions`, `technology_stage_history`, `stock_prices` (both never-pruned),
   `company_financials`, `strategist_briefs`, and the 8 `*_articles` feed tables
   via `PulseAggregator.all_recent(45)`.
2. **Artifact scan**: run `python backend/forecast_reset.py` (no `--apply` — dry-run) →
   expect 0 auto rows with `resolved_on − made_on < 7`.
3. **Hand-verify 3-5 resolved records, one per auto kind**:
   - a `stage_advance`: re-derive the verdict from `technology_stage_history`
     rows for the subject in `(made_on, resolve_by]` and diff vs
     `resolution_evidence.stages_seen`;
   - a `price_move`: recompute the point-to-point return from `stock_prices`
     closes at made_on/resolve_by and diff vs `resolution_note`'s `%`;
   - a `deal_flow`/`reactivity`: compare `resolution_evidence.deals_since` /
     `moves_pct` against the note (feed rows may have pruned — the snapshot is
     the audit trail; flag any resolved row with a NULL snapshot).
4. **Recompute the scorecard offline** from the dumped rows with
   `fc.track_record` / `fc.brier_score` / `fc.calibration_bins` and diff against
   `GET /api/forecasts` (headline, categories, bins) — must match exactly.
5. **Quarantine audit**: assert every `kind='price_move'` row lands in
   "Price (low-signal)" and the per-category sums reconcile to the headline totals.
6. **Look-ahead sweep**: assert for every resolved auto row
   `resolved_on > made_on`, `resolved_on − made_on ≥ 7`, and for hits the
   evidence dates fall in `(made_on, resolve_by]`.

Guards: SELECT-only client; no `--apply`; no `.env` values echoed anywhere.

---

**Acceptance targets:** look-ahead violations found in code: **0** (PASS) ·
Brier/calibration hand-check: **exact match** (PASS) · quarantine: **partial —
category wall correct, but headline stats still pool price calls** (FAIL at the
"100%" bar as literally stated).

---

## Live backtest results (2026-07-02)

Mode: APPROVED live run, **SELECT-only** (all reads via `db.get_supabase()`, the
same client path as `analytics/run_ledger.py`). Zero writes, zero LLM calls,
`forecast_reset` **not** run — its predicate was evaluated offline on fetched
rows. No `.env` values read or echoed.

### Ledger census

- **266 rows** total (`made_on` 2026-06-12 → 2026-07-02): **230 open / 36
  resolved** (32 hit / 4 miss / 0 partial). Sources: 118 quant, 148 strategist.
- Per kind (open + resolved → outcomes):
  `manual` 148 (all open) · `price_move` 40 (all open) · `reactivity` 23
  (7 open, 16 resolved → 16 hit) · `deal_flow` 22 (7 open, 15 resolved →
  15 hit) · `stage_advance` 21 (20 open, 1 resolved → 1 hit) ·
  `posture_persist` 12 (8 open, 4 resolved → 4 miss).
- Per category: Strategist (judgment) 148 · Price (low-signal) 40 · Market
  structure 34 · Market reactivity 23 · Technology 21.
- **0** resolved auto rows with a NULL `resolution_evidence` snapshot.

### LOCKED-WHEN-MADE — PASS (with one benign cohort finding)

- All 266 rows: `date(created_at) == made_on`; every resolved row has
  `resolved_on > made_on` and `resolved_on ≥ created_at`; every open row has
  NULL `outcome/resolved_on/resolution_note`; all resolved outcomes valid.
- **Fingerprint recompute:** for all 118 auto rows,
  `sha1(kind|subject|made_on)[:16]` recomputed offline **matches the stored
  fingerprint exactly** — kind/subject/made_on provably unmutated since insert.
- Kind-specific timing invariants hold: no `posture_persist` HIT before
  `resolve_by`, no `price_move` resolved before `resolve_by` (none resolved at
  all), no overdue-miss fired at or before `resolve_by`.
- **Cohort finding (not a mutation):** the 27 auto rows made on 2026-06-12/13
  (ids 2–85) carry `resolve_by − made_on = 90d` instead of the kind-specific
  windows (180d stage_advance, 30d deal_flow/reactivity). The 06-13
  `stage_advance` cohort contains *both* 90d and 180d rows — the `resolve_days`
  pin (`forecasts.py:_mk`) landed mid-day 2026-06-13, and the pre-fix rows were
  **left untouched**. This is locked-when-made working as designed (no
  retro-edit), but note the side effect: the old cohort's overdue→miss backstop
  fires at 90d, not the ~1-month the claim text promises — softer grading for
  those 27 rows only. All 7 resolved deal_flow rows from that cohort hit well
  inside 30d anyway, so no grade actually changed.

### NO LOOK-AHEAD — PASS (35/36 fully re-derived; 1 unreproducible post-prune)

Every resolved auto forecast (all 36) re-derived offline using only evidence
dated inside `(made_on, min(resolve_by, resolved_on)]`:

- `stage_advance` (1/1): id 53 re-derived from `technology_stage_history` →
  HIT, note identical ("adoption reached 'early-adopters' by 2026-06-14";
  made 06-12, resolved 06-19 — 7d gate respected). Evidence `stages_seen`
  consistent with the table.
- `price_move` (0 resolved): nothing to re-derive; earliest `resolve_by` is
  2026-09-10.
- `deal_flow` (15/15 evidence-consistent; 14/15 live-recounted ≥ threshold):
  every snapshot `deals_since ≥ threshold` matches its note. Live recounts from
  the retained feed window confirm 14 of 15. **id 83** (Auto & EV, made 06-13,
  resolved 06-21, snapshot `deals_since=3`) recounts to **0** today: the window
  is partially pruned (`home_news_articles` now retains only ≥ 06-18) and
  re-ingest/classification churn moved rows (other ids recount 16 vs 8, 6 vs 2
  — churn goes both directions). `_is_capital_row` is unchanged in git since
  before 06-21. This is the documented degrade mode the `resolution_evidence`
  column exists for — the snapshot is the audit trail — and it is **not a
  look-ahead signature** (look-ahead would require deals dated ≤ made_on; the
  counter filters `published_at > made_on` strictly and pruning cannot forge
  that). Verdict: unreproducible from retained rows, internally consistent.
- `reactivity` (16/16): every snapshot `moves_pct` contains ≥1 move ≥ the
  locked `threshold_pct`, matching the stored HIT.
- `posture_persist` (4/4): all 4 misses are tilt flips (`tilt_now` ≠ locked
  `params.tilt` in every snapshot) — the valid early-MISS path; none claims a
  pre-`resolve_by` HIT.

### BRIER + CALIBRATION — offline vs API: EXACT MATCH

Offline recompute (`fc.track_record` / `calibration_bins` /
`track_record_by_category` / `calibration_headline` on the fetched rows) vs
`backend.app.forecasts.build_forecasts()` called in-process (no server):
**every field identical** — track_record, categories, bins, headline
(state=`live`, verdict=`well-calibrated`).

- Headline: accuracy **0.889**, Brier **0.119** over 36 resolved (exact:
  0.8889 / 0.1192).
- Bins: 40–60% → actual 0.20 (n=5, the posture misses); 60–80% → 1.00 (n=23);
  80–100% → 1.00 (n=8). Read: the record is **under-confident** in the upper
  bands, not over-confident.
- Per-category sums reconcile exactly to the headline totals.

### QUARANTINE LEAK — structurally present, currently zero, projected large

- Headline WITH price pooled: accuracy 0.889 / Brier 0.119.
  Headline WITHOUT `price_move`: accuracy 0.889 / Brier 0.119.
  **Delta today: +0.000 / +0.000** — because **0 of the 40 price calls have
  resolved** (all open, `resolve_by` 2026-09-10 → 09-22).
- The leak is latent, not hypothetical: all 40 sit at pinned 0.50 confidence in
  the pooled headline path. Once they mature as the coin flips the code itself
  expects, the headline moves to **accuracy ≈ 0.684, Brier ≈ 0.188**
  (0.889→0.684, 0.119→0.188) with zero change in forecasting skill — the
  "can't flatter the headline" copy will be visibly wrong in ~10 weeks.
- Category wall itself is correct: all 40 land in "Price (low-signal)" and
  category sums reconcile.

### Same-day-HIT / fast-resolve artifacts — NONE

0 auto rows resolved < 7 days after `made_on` (min observed gap: 7d, id 53);
0 same-day HITs; `forecast_reset.is_premature_resolution` (evaluated offline on
the fetched rows — CLI not run) flags **0** rows.

### Anomalous records by id

| ids | Finding | Severity |
|---|---|---|
| 2–5, 8, 15–18, 47–54, 57–59, 69–71, 77, 83–85 (27 rows) | pre-2026-06-13 cohort: `resolve_by` = 90d, not the kind's current window | Info — proves immutability; slightly soft overdue backstop for this cohort |
| 83 | resolved deal_flow whose window can no longer be recounted from retained feed rows (pruning + churn); snapshot internally consistent | Low — documented degrade mode; audit rests on the snapshot |

### Acceptance verdict vs targets

| Target | Result |
|---|---|
| 0 look-ahead violations | **PASS** — 0 found on real data; 35/36 resolutions fully re-derived, 1 unreproducible post-prune (not a look-ahead signature) |
| Brier/calibration hand-check exact | **PASS** — offline recompute == API output, field-for-field |
| Quarantine 100% | **FAIL (as expected)** — headline pools price calls; magnitude today 0.000/0.000 (none resolved), projected −20.5pp accuracy / +0.069 Brier when the 40-call cohort matures (Sep 2026) |
| Locked-when-made on real data | **PASS** — fingerprints recompute exactly; no post-hoc mutation signatures; no same-day artifacts |
