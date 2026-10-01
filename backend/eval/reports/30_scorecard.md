# Phase 3 — Lodestar Eval Scorecard & Synthesis

Date: 2026-07-02 · Sources: `backend/eval/reports/00–10` (layer reports incl. live results),
`20_product_completeness.md` (council). Companion workbook:
`lodestar_eval_scorecard.xlsx`. Gold-set caveat: L3 numbers are against the
**provisional** gold (199 rows, triage-corrected; human sign-off on 36 rows pending).

## 1. The scorecard — actual vs pre-committed target, per layer

Dimensions: C = correctness · F = faithfulness/grounding · T = theory fidelity ·
K = calibration · P = product completeness.

| Layer | Metric (dim) | Target | Actual | Verdict |
|---|---|---|---|---|
| **L1 Prompts** | Schema drift, 13 prompts (C) | 0 | **0** | ✅ PASS (GATE) |
| | Rubric ≥80% each (C) | 13/13 Green | 11/13 (Strategist 70.8%, Ask 75.0%) | ❌ FAIL |
| **L2 Extraction** | Strictly grounded (F) | ≥90% | **84.0%** (79/94) | ❌ FAIL |
| | Fabrications (F) | 0 | **3** (BlackRock; 916→674 turbines; 63 kWh) | ❌ FAIL |
| | Provenance coverage (F) | ≥95% | **95.6%** | ✅ PASS |
| | Cross-feed dup URLs (C) | 0 | 1 in sample (+53 slash-dups) | ❌ FAIL |
| **L3 MOT Lens** ⭐ | Gold set ≥150 human-verified (—) | ≥150 | 199 provisional, **0 human-signed** | ⏳ PENDING |
| | maturity exact / within-1 (C) | ≥70% / ≥90% | **69.2%** (CI 61–76) / **82.9%** | ❌ marginal FAIL / FAIL |
| | adoption exact / within-1 (C) | ≥65% / ≥90% | **71.9%** / **86.3%** | ✅ PASS / ❌ FAIL |
| | business_impact / scope (C) | ≥80% / ≥80% | **94.5%** / **95.9%** | ✅ PASS |
| | Stage errors adjacent (K) | ≥80% | 80% (maturity), 95% (adoption) of stage↔stage; but 44% of all maturity errors involve n/a | ⚠️ PASS w/ n/a caveat |
| | A/B v1 stored vs v2 fresh (C) | v2 ≥ v1 | v2 **−5.5 pp** maturity, **−6.8 pp** adoption | ❌ deployed prompt not better |
| **L4 Rollup** | Recompute drift (C) | 0 | **0** across 232 feed-days, 10 feeds | ✅ PASS |
| | Known bugs (C) | — | 3 (query-string dedup; momentum off-by-one; breakdown unchecked) | ⚠️ open |
| **L5 Tech layer** | Golden fixtures (C) | 100% | 100% (16 added; 1 xfail pins modal-vs-committed gap) | ✅ PASS |
| | Cross-surface stage disagreement (P) | 0 | **0** (verified single `display_stage()`) | ✅ PASS |
| **L6 Financials** | Fundamentals ±5% of source (C) | 5/5 | **3/5** — Samsung **+12.8%**, ASML −5.7% (stale FX) | ❌ FAIL |
| | Event-study baseline (C) | 100% | verified strictly-before on live NVDA event | ✅ PASS |
| | Fiscal-period alignment (C) | correct | `_first()` can mix years (0/5 fired today; latent) | ⚠️ open |
| **L7 Forecasts** | Look-ahead violations (K) | 0 | **0** (35/36 re-derived; 36th snapshot-audited) | ✅ PASS |
| | Brier/calibration recompute (K) | exact | **exact** (0.889 acc / 0.119 Brier; under-confident) | ✅ PASS |
| | Locked-when-made (K) | holds | all 118 fingerprints recompute; no mutation path | ✅ PASS |
| | Price-call quarantine (K) | 100% | headline pools them — **latent −20.5 pp cliff ~Sep 2026** | ❌ FAIL |
| **L8 Strategist** | Numeric grounding (F) | ≥95%, 0 hallucinated | **100% adjudicated** (4 flags were unit conversions), 0 fabrications | ✅ PASS |
| | S#/T# reference validity (F) | 100% | **100%** | ✅ PASS |
| | Theory fidelity mean (T) | ≥2.0/3, 0 misapplications | **1.6/3, 2 misapplications** (dominant-design off 1–2 pts; post-hoc chasm) | ❌ FAIL |
| | Falsifier quality (K) | ≥9/12, none missing | **10.8/12**, none missing/non-refuting | ✅ PASS |
| | Overclaim rate (T) | ≤10% | **20–40%** | ❌ FAIL |
| **L9 Ask** | Retrieval precision@5 (C) | ≥0.80 | **0.94** (in-session judged) | ✅ PASS |
| | Phantom-citation guard (F) | exists | **absent in production** (static); live unmeasured | ❌ FAIL |
| | Faithfulness / refusal (F) | 0 ungrounded / ≥90% | **unmeasured — `TOQAN_ASK` empty in .env** | ⏳ BLOCKED |
| **L10 App** | Filters change view (P) | 100% | **21/21 wired**, 0 console errors, 7/7 tabs live | ✅ PASS |
| | Unrendered API fields (P) | 0 | **8 top-level + nested** (incl. duplicated adoption insight) | ❌ FAIL |
| | Cross-tab contradictions (P) | 0 | 1 ("Coverage" ≠ same number MOT vs Explore) + backward transitions hidden | ❌ FAIL |

**Tally: 17 PASS · 12 FAIL · 2 PENDING/BLOCKED · 3 open bug clusters.**
Pattern: the **accountability machinery passes everything** (ledger, rollups,
event study, falsifiers, grounding, app wiring); the failures cluster in **inputs**
(FX, extraction fabrications, lens n/a boundary) and **interpretation** (theory
fidelity, overclaims) — plus one time bomb (the September headline cliff).

## 2. Prioritized fix backlog

**P0 — trust blockers (fix before showing anyone):**

| # | Fix | Layer | Effort | Evidence |
|---|---|---|---|---|
| 1 | Dated live FX (replace static map; store rate + as-of) | L6 | S | Samsung +12.8% live |
| 2 | Exclude quarantined price calls from headline accuracy/Brier | L7 | S | −20.5 pp cliff ~Sep 2026 |
| 3 | Ask citation guard (range-check `[S#]/[T#]`); drop "answer from doctrine" fallback; populate `TOQAN_ASK` | L9 | S | phantom-by-construction |
| 4 | Lens n/a gate in MOT Lens prompt (corp-finance → n/a; funding ≠ chasm; boundary debias) → re-run `lens_ab.py` | L3 | M | 44% of maturity errors are n/a-boundary; A/B tool ready |
| 5 | Pre-write groundedness check (entities + numbers in summary must appear in source) | L2 | M | 3 live fabrications passed all validation |
| 6 | Commit the working-tree `backend/app/mot.py` scope fix | L10 | XS | at HEAD the filter is a no-op |
| 7 | Fiscal-period alignment in `finance/client.py::_first()` (one statement column for all fields) | L6 | S | 2× R&D-intensity repro |
| 8 | URL normalization + cross-feed dedup at write time | L2/L4 | M | 1 cross-feed + 53 slash dups live |

**P1 — quality:**

| # | Fix | Layer | Effort |
|---|---|---|---|
| 9 | Strategist prompt rewrite: worked examples, sparse-pack rule, overclaim ban, precondition-evidencing requirement | L1/L8 | M |
| 10 | Ask prompt: refusal example + phantom-citation ban; version headers on all 12 unversioned prompts | L1 | S |
| 11 | Momentum off-by-one (`trends.py`) + add `by_company_breakdown` to rollup integrity | L4 | S |
| 12 | Guard `POST /api/forecasts/resolve` (kind/status check) | L7 | XS |
| 13 | Persist committed (not modal) stage to history | L5 | S |
| 14 | Restore backward transitions in UI; delete or differentiate `adoption_interpret`; render or drop the 8 dead fields | L10 | S |
| 15 | Small-base threshold on trend % (kills "+13155%") | L4/UI | XS |
| 16 | `tags` provenance; ledger dropped-item identities | L2 | XS |

**P2 — product (council backlog, `20_product_completeness.md` §C items 9–14):**
public timestamped ledger page → run + publish theory-fidelity scores → API keys +
custom registry + transition alerts → transition-vs-outcome validation study →
rolling gold refresh + point-in-time labels → leading-signal expansion or
one-vertical depth.

## 3. Executive read — is Lodestar defensible for the strategy team?

**Yes for internal use today; not yet for external/board use — and the gap is
narrow, cheap, and precisely mapped.**

The expensive claim — *"the intelligence that grades itself"* — survived a hostile
audit. The forecast ledger is provably locked-when-made, resolution has zero
look-ahead, the Brier/calibration math is exact (and under-confident, the honest
direction), rollups recompute to zero drift, the event-study baseline is leak-free,
and every UI control does what it says. That machinery is the moat, and it is real.

**Top 3 risks (scored, not vibes):**
1. **Wrong numbers on trust surfaces.** A 2-year-stale FX map inflates Samsung
   +12.8% on the flagship exhibit; the 89% forecast headline will mechanically
   collapse to ~68% around September when 40 pooled coin-flip price calls mature.
   Both are small fixes; both are reputational time bombs if someone else finds them.
2. **The classification root is soft where it matters.** Maturity misses its bar
   (69.2% exact, 82.9% within-1), driven by a promptable n/a-boundary failure —
   and the deployed lens prompt scores *worse* than the stored history (−5.5/−6.8 pp).
   Every S-curve, transition, and stage forecast inherits this.
3. **Interpretation outruns evidence.** Theory fidelity 1.6/3 with two confirmed
   misapplications and 20–40% overclaim; extraction fabricated entities/numbers in
   3/94 sampled items with no groundedness check to catch them.

**Top 3 strengths:** (1) verified accountability machinery (ledger/rollup/
event-study/falsifiers 10.8/12) that incumbents structurally can't copy;
(2) unified technology-stage data model — zero cross-surface disagreement, debounced,
direction-aware; (3) this eval harness itself — drift checkers, judges, A/B, and a
199-row gold set make every future prompt/model change (Fable 5) measurable in one
command. The Fable 5 baseline to beat is now on record: **lens 63.0%/63.7%
single-shot; theory fidelity 1.6/3; overclaim 20%.**

**The quarter's plan is the council's one bet:** P0 fixes (~2 weeks) → gated lens
re-A/B → publish the graded ledger. Build no new exhibits until the known-wrong
numbers are gone.

## 4. Eval-method upgrades applied (2026 practice)

Wilson CIs on all gold-set accuracies (§1); judge-calibration kappa pending your
36-row review (free measurement); Ragas-style metric naming for L9 in the workbook;
rolling-gold-refresh + continuous-eval schedule to be baked into the Phase 4 skill.
In-session judging (B, F, G-retrieval) is flagged in each report; correlated-judge
bias applies — the Phase 4 skill should re-run F with independent Toqan judges when
`TOQAN_JUDGE` is provisioned.

---

## 5. P0 fixes applied (2026-07-02, same session)

All eight P0 items closed in code (suite: 414 passed + 1 xfail; tier 0 runner green):

| # | Fix | Status |
|---|---|---|
| 1 | Dated live FX (batched write-time fetch; refreshed dated fallback; unknown-currency warnings) | ✅ done — FX source/as-of logged, not yet stored (needs schema migration → P1) |
| 2 | Headline excludes quarantined price calls (analytics layer; all consumers inherit; honest labels on every surface) | ✅ done — Sept cliff defused |
| 3 | Ask citation guard (`[unverified]` neutralization) + doctrine-fallback removed | ✅ done — `TOQAN_ASK` still empty (user) |
| 4 | Lens prompt v4: n/a gate, funding≠adoption, boundary debias, 4 worked examples; `LENS_PROMPT_VERSION` bumped | ✅ done — **user must paste v4 into Toqan before next feed run**, then re-run `lens_ab.py` (baseline: 63.0%/63.7%) |
| 5 | Pre-write groundedness check (vs the og:image page fetch; flag-not-drop via `provenance["groundedness"]`) | ✅ done — all 3 live fabrications pinned by tests |
| 6 | Commit working-tree `backend/app/mot.py` scope fix | ⏳ user commit decision |
| 7 | Fiscal-period anchor column in `finance/client.py` | ✅ done — 2× repro now yields honest `None` |
| 8 | URL canonicalization + cross-feed dedup + aggregator query-param fix | ✅ done — caveat: rollup-integrity recompute may show expected diffs on pre-fix days |

## 6. P1 fixes applied (2026-07-02, same session)

All eight P1 items closed (suite: **446 passed, 0 xfail**; drift audit 0; tsc clean; tier 0 runner 8/8; parity findings 8 → 1):

| # | Fix | Outcome |
|---|---|---|
| 9 | Strategist prompt → **strategist-v2**: evidence-before-labels, calibrated-language ban, sparse-pack rule, 2 worked examples (self-scored 70.8% → 100%) | ✅ re-paste into Toqan |
| 10 | Ask prompt → **ask-v2** (refusal + phantom ban + buy/sell decline); version headers + empty-[] path on all 10 extractors; OUTPUT CONTRACT added to AI-Energy + EV | ✅ re-paste into Toqan |
| 11 | Momentum off-by-one fixed via shared `half_split` (3 call sites); `by_company_breakdown` now integrity-checked | ✅ |
| 12 | Resolve endpoint guarded (404/400/409 + race guard); resolver UI surfaces rejections | ✅ |
| 13 | `snapshot()` persists committed stage; xfail flipped to passing; inline stage copies collapsed | ✅ |
| 14 | Backward transitions restored (expander); duplicate `adoption_interpret` dropped; Explore marginals + adopter tooltips + degraded-state notices rendered; "Coverage" renamed; dead module deleted; Forecasts `Type`/`Horizon` rendered, dupes dropped | ✅ |
| 15 | Small-base guard (<5) on trend %; "+13155%" impossible | ✅ |
| 16 | `tags` provenance + dropped-item identities ledgered to feed_runs | ✅ |

**Toqan re-paste queue (nothing takes effect until pasted):** MOT_Lens_Agent.md (v4),
Strategist_Agent.md (v2), Ask_Bellwether_Agent.md (v2); extractor prompts optional
(headers + empty-[] hardening). After pasting: re-run `lens_ab.py` (baseline
63.0%/63.7%) and `strategist_eval.py --from-supabase` on the next fresh brief
(baseline fidelity 1.6/3, overclaim 20%).

## 7. Lens v4 A/B outcome (2026-07-02, evening) — REVERTED to v3

The deployed v4 prompt measured **worse** on the provisional gold (n=146): maturity
52.1% vs v3's 63.0% (−10.9pp), adoption 58.2% vs 63.7% (−5.5pp) — full output in
`lens_ab_v4_20260702.txt`. Ambiguity: over-corrected prompt vs v3-echoing gold set
(164/199 rows are unreviewed lens guesses). **Action taken:** prompt reverted to v3
(v4 preserved at `backend/Agents_prompt/drafts/MOT_Lens_Agent_v4_DRAFT.md`),
`LENS_PROMPT_VERSION` back to v3; user re-pastes v3 into Toqan. **The 36-row human
gold review is now the decisive tiebreaker** — after it, refine the v4 draft
against honest gold and re-A/B.
