# L8 — Strategist (headline briefing) — offline eval + judge harness

Date: 2026-07-02 · Branch: `main` · **Offline only** — no Supabase reads, no Toqan
calls, `.env` untouched, no production code modified.

Deliverables landed by this phase:
- `backend/eval/judges/strategist_eval.py` — the L8 judge harness (deterministic checks + gated LLM panel)
- `backend/eval/judges/fixtures/brief_clean.json`, `brief_defective.json` — synthetic fixture briefs
- `tests/test_strategist_eval.py` — 14 tests pinning the harness

---

## 1. Unit suite (regression floor)

```
./venv/bin/python -m pytest tests/test_strategist.py -q
25 passed, 1 warning in 0.26s          # warning = supabase/gotrue deprecation, not ours
```

Full suite after adding the harness tests: `./venv/bin/python -m pytest -q` →
**379 passed, 1 xfailed** (includes the new `tests/test_strategist_eval.py`, 14 tests).

## 2. What L8 actually is (from reading the source)

`analytics/strategist.py` (766 lines) + `backend/Agents_prompt/Strategist_Agent.md`:

- **Pipeline.** `Strategist.generate()` gathers material stories (`PulseAggregator.targeted_recent`,
  14-day window, ≤18 stories), retrieves ≤8 MOT theory passages (pgvector KB), adds
  technology-trajectory + financial context, builds a numbered data pack
  (`[S1..Sn]` developments, `[T1..Tk]` theory), and calls Toqan
  (`ToqanAgent(api_key=os.getenv("TOQAN_STRATEGIST"), agent_name="Strategist Agent")`).
- **Signal schema** (enforced by `_normalize_structured`, tolerant coercion): per signal
  `title / lens / implication / action∈{enter,scale,defend,partner,wait,exit} /
  action_rationale / impact∈{high,med,low} / horizon∈{near,mid,long} / value_capture /
  standards{leader,basis,read} / falsifier / sources[S#] / confidence`. Signals sorted
  by impact×confidence. Plus brief-level `bottom_line`, `confidence`, `convergence[]`,
  `scenarios{base,bull,bear}`, `watch[]`.
- **Where S# refs and numbers come from.** The pack numbers the stories `[S1]…`; the
  prompt contract says every signal must cite ≥1 `S#` and "never invent developments,
  figures, companies, or theory not in the pack". Numeric claims should therefore trace
  to the pack: story titles/summaries, the financial-context block (R&D intensity,
  price reactions), and the trajectory block.
- **Storage.** The row upserted to `strategist_briefs` (`on_conflict="as_of,focus"`)
  carries `strategic_read` **plus the exact slimmed source set** (`stories` with
  `label:"S{i}"`, `theory` with `label:"T{i}"`). This is the key eval affordance: a
  stored brief is *self-contained* — grounding and S#-validity are checkable offline
  against the row itself, no re-fetch needed. The harness consumes exactly this row shape.
- **Nothing in code validates content.** `_normalize_structured` coerces enums but never
  checks that `sources` resolve, that numbers exist in the pack, or that falsifiers are
  dated — that is precisely the gap L8's judge harness covers.

## 3. The harness — `backend/eval/judges/strategist_eval.py`

```
./venv/bin/python -m eval.judges.strategist_eval --from-fixture <brief.json> [--json]
./venv/bin/python -m eval.judges.strategist_eval --from-supabase        # STUB: NEEDS APPROVAL
./venv/bin/python -m eval.judges.strategist_eval --from-fixture ... --live-judge   # GATED
```

**Deterministic checks (offline, no LLM):**

1. **Grounding.** Numeric-claim extraction (regex: currency/percent/scale words/attached
   units like `2nm`/`3.2bn`) from `title/implication/action_rationale/value_capture/standards.read`
   — the **falsifier is excluded** (its numbers are forward-looking thresholds, not source
   claims). Normalized matching against the signal's cited stories: mantissa with digit
   boundaries, unit-token substring, and scale-equivalent canonical value
   (`€3.2 billion` == `3.2bn`; `90%` == `90 percent`). Three outcomes: **grounded**
   (in a cited source), **misattributed** (only in an uncited source — warn),
   **hallucinated** (in no source). Bare years and single-digit counts are *advisory*
   (reported, not scored).
2. **S#/T# validity.** Every id in `sources[]` and every inline `[S#]`/`[T#]` must resolve
   to a label in the stored `stories`/`theory` sets; empty `sources[]` flagged (contract
   requires ≥1).
3. **Falsifier mechanical** (the machine-checkable half of `backend/eval/rubrics/falsifier.md`):
   presence, criterion 2 *time-bound* (year/quarter/month/"within N months" regex; bare
   "may" deliberately excluded — modal-verb collision), criterion 4 *measurable threshold*
   (comparator+number, currency, or %/scaled number). 0–4 per signal. Criteria 1/3/5/6
   (specific, refuting, checkable, non-trivial) need the LLM panel.
4. **Overclaim.** Lexicon (`wins, confirms, proves, guarantees, inevitable, will dominate, …`;
   "locking in" deliberately absent — it is sanctioned lens vocabulary) + evidence-strength
   heuristic: a hit is a **violation** unless `confidence == high` AND ≥2 valid cited
   sources (the rubric's corroboration bar). Falsifier text exempt (hypotheticals).

**LLM-judge panel (gated).** 3 independent judges per signal — two scholar judges + one
explicitly prompted to **REFUTE** (steelman the refutation first) — each scoring both
rubrics (`mot_scholar.md` theory fidelity 0–3 + misapplication flag; `falsifier.md`
six criteria /12). Prompt templates live in the file (`SCHOLAR_JUDGE_PROMPT`,
`REFUTER_JUDGE_PROMPT`) and embed the rubric files verbatim. **Majority rules**: median
score per signal; misapplication/overclaim/non-refuting stand only if ≥2 of 3 judges flag.
Wiring mirrors `lens_ab.py`/`analytics/strategist.py` (`toqan.client.ToqanAgent`), but:
imports are lazy, the key is a *dedicated* `TOQAN_JUDGE` env var (never the Strategist's),
and without it `run_live_panel` raises `NEEDS APPROVAL` before any network code loads.
`build_judge_prompts()` is pure and runs offline (used to count/inspect the calls a live
run would make).

**Exit codes:** 0 = all deterministic targets met · 1 = a target failed · 2 = gated path refused.

## 4. Fixture demo — the checks catch the seeded defects

Two synthetic briefs under `backend/eval/judges/fixtures/` in the exact `strategist_briefs` row shape.

**Clean** (`brief_clean.json` — includes normalization traps: brief says "€3.2 billion",
source says "3.2bn"; brief "90%", source "90 percent"):

```
L8 Strategist — deterministic scorecard (as_of=2026-07-01, focus=daily, signals=3)

  Grounding        : 100.0%  (6/6 hard numeric claims in cited sources; target >=95% & 0 hallucinated)
  S#/T# validity   : 100.0%  (11/11 refs resolve; target 100%)
  Falsifier (mech) : mean 4.0/4  (dated 0/2 + threshold 0/2; full /12 needs the LLM panel)
    signal 1: 4/4 — "Samsung or Intel wins more than 20% of 2nm-class orders by Q2 2027"
    signal 2: 4/4 — "Fewer than 2 subsidized gigafactories reach volume production by end of 2028"
    signal 3: 4/4 — "Follow-on tranche is cancelled or cut below $200 million by Q1 2027"
  Overclaim rate   : 0.0%  (0/3 signals; target <=10%)

  VERDICT: PASS — all deterministic L8 targets met

  LLM panel not run (pass --live-judge; would make 9 Toqan calls = 3 signals x 3 judges; NEEDS APPROVAL)
```
Exit code 0. (Note: signal 1's falsifier contains "wins" — correctly *not* flagged, falsifiers are exempt.)

**Defective** (`brief_defective.json` — 5 seeded defects, **all caught**):

```
L8 Strategist — deterministic scorecard (as_of=2026-07-01, focus=daily, signals=3)

  Grounding        : 33.3%  (1/3 hard numeric claims in cited sources; target >=95% & 0 hallucinated)
    HALLUCINATED   : signal 1 "Anthropic-scale inference round resets capital bar" — '$4.5 billion' appears in NO source
    misattributed  : signal 3 — '80,000' found only in sources the signal did not cite
  S#/T# validity   : 85.7%  (6/7 refs resolve; target 100%)
    PHANTOM REF    : signal 2 "Nvidia takes the inference market" cites S9 — no such item in the brief's source set
  Falsifier (mech) : mean 2.67/4  (dated 0/2 + threshold 0/2; full /12 needs the LLM panel)
    signal 1: 4/4 — "Round is downsized below $1 billion or shelved by Q4 2026"
    signal 2: 4/4 — "AMD or a hyperscaler ASIC takes more than 15% of inference shipments by Q2 2027"
    signal 3: 0/4 — "Enterprise adoption may slow if interest fades"  <- UNDATED, NO THRESHOLD
  Overclaim rate   : 33.3%  (1/3 signals; target <=10%)
    OVERCLAIM      : signal 2 "Nvidia takes the inference market" uses ['confirms', 'wins'] with confidence=medium, 1 valid source(s) — evidence too weak

  VERDICT: FAIL — failed: grounding_pct_ge_95, zero_hallucinated_numbers, sref_100pct_valid, falsifier_mech_mean_ge_3of4, overclaim_rate_le_10pct

  LLM panel not run (pass --live-judge; would make 9 Toqan calls = 3 signals x 3 judges; NEEDS APPROVAL)
```
Exit code 1.

| Seeded defect | Caught by |
|---|---|
| Hallucinated `$4.5 billion` (source says `$2.1 billion`) | Grounding → HALLUCINATED |
| Phantom `S9` in `sources[]` | S# validity → PHANTOM REF |
| Undated, threshold-free falsifier ("adoption may slow…") | Falsifier mech → 0/4 |
| "confirms … wins" on medium confidence / 1 source | Overclaim → violation |
| `80,000` cited to S3 but only in S4 | Grounding → misattributed (warn) |

Gated paths verified: `--from-supabase` → `NEEDS APPROVAL` stub (exit 2);
`--live-judge` without `TOQAN_JUDGE` → prints the deterministic scorecard then
`NEEDS APPROVAL` (exit 2). Pinned in `tests/test_strategist_eval.py::test_live_paths_are_gated`.

## 5. Acceptance targets — coverage map

| Target | Checked by | Status on fixtures |
|---|---|---|
| Grounding ≥95%, 0 hallucinated numbers | deterministic (offline) | clean 100% / defective caught |
| S# validity 100% | deterministic (offline) | clean 100% / phantom caught |
| Falsifier: none missing, dated + threshold | deterministic (mechanical half) | clean 4/4 / undated caught |
| Falsifier mean ≥9/12, none non-refuting | **LLM panel (live)** — criteria 1,3,5,6 | prompts ready, gated |
| Theory fidelity mean ≥2.0, 0 misapplications | **LLM panel (live)** — mot_scholar rubric | prompts ready, gated |
| Overclaim ≤10% | deterministic lexicon + heuristic; panel corroborates | clean 0% / seeded caught |

## 6. PROPOSED live run — **NEEDS APPROVAL, not executed**

1. **Supabase read (1 query, read-only):** un-stub `load_from_supabase` →
   `Strategist(get_supabase()).latest("daily")`; the row already contains
   `strategic_read` + `stories` + `theory`, so deterministic checks run on it as-is.
   Nothing is ever written back (lens_ab.py's non-destructive pattern).
2. **Deterministic pass first** (free): if grounding/S#/falsifier-mech/overclaim already
   fail, fix before spending judge calls.
3. **LLM panel via Toqan:** a real brief has 3–5 signals (prompt contract) →
   **9–15 Toqan calls** (signals × 3 judges), one-shot, no retries beyond the client's
   built-in ones. Requires a dedicated judge key exported as `TOQAN_JUDGE` (a plain
   Toqan agent or the Ask agent's key — *not* `TOQAN_STRATEGIST`, to keep the judge
   independent of the system under test). Aggregation (median + ≥2/3 majority) and the
   scholar/refuter prompts are already implemented; zero code changes needed beyond the
   two un-gates.
4. **Report:** re-run `--from-supabase --live-judge --json`, append the scorecard here,
   score against the §5 targets, and hand misapplications / non-refuting falsifiers to
   the fix backlog.

**Cost estimate: 1 Supabase read + 9–15 Toqan LLM calls. Awaiting explicit user approval.**

## 7. Findings & caveats

- **The stored row is the right eval unit.** Because `generate()` persists the slimmed
  `[S#]`/`[T#]` sets alongside the read, L8 grounding is fully auditable offline for any
  historical brief — the harness needs only the row.
- **Production has no content validation** (only enum coercion); the deterministic layer
  here is cheap enough to run post-`generate()` as a guard if desired (out of scope —
  no production changes made).
- **Known heuristic limits** (by design, documented in the code): unscaled-vs-scaled
  mantissa matches ("$6.6bn" vs a source saying only "6.6") are accepted; the overclaim
  lexicon is a floor, not a semantic check — the refuter judge covers the rest;
  falsifier criteria 1/3/5/6 are judge-only.

## Live judging results (2026-07-02)

**Executed:** step F (approved). `load_from_supabase()` un-stubbed in
`backend/eval/judges/strategist_eval.py` — one read-only SELECT on `strategist_briefs`
(latest `focus=daily` row: `as_of=2026-07-02`, generated 11:24 UTC, 5 signals,
18 S# stories + 8 T# theory passages embedded in the row). No writes.

> **Caveat — panel substitution.** The approved 9–15 Toqan judge calls were NOT
> made. Per instruction, the judging below is an in-session panel-of-passes: the
> evaluating model made three independent rubric passes per signal (scholar,
> value-capture scholar, adversarial refuter) and took medians. This is cheaper
> and traceable but NOT three independent models — correlated-judge bias applies.
> Treat fidelity/falsifier numbers as provisional until a true independent panel runs.

### Deterministic scorecard (real brief)

| Check | Result | Target | Verdict |
|---|---|---|---|
| Grounding | **69.2%** (9/13 hard claims) | ≥95% | **FAIL (raw)** — but see adjudication |
| Hallucinated numbers | 4 flagged | 0 | **0 true fabrications** after audit |
| S#/T# validity | 100% (11/11 refs) | 100% | **PASS** |
| Falsifier mechanical | mean 3.2/4, none missing | ≥3.0, none missing | **PASS** |
| Overclaim (lexicon) | 20% (1/5: S2 "confirmed", medium conf, 1 source) | ≤10% | **FAIL** |

**Grounding audit — all four "hallucinated" numbers are conversions of real cited
figures, not fabrications:**

| Flagged claim | Signal | Source text | Nature |
|---|---|---|---|
| `107K` | 3 | S10: "107,658 vehicles" | truncation/rounding |
| `557K` | 3 | S11: "557,090 battery electric vehicles" | rounding |
| `2.45` (GW) | 4 | S15: "2,450 MW of solar" | MW→GW unit conversion |
| `6.4` (GWh) | 4 | S15: "1,600 MW / 6,400 MWh battery" | MWh→GWh unit conversion |

Adjudicated grounding: **13/13 traceable to cited sources, 0 fabricated**. The
raw 69.2% is a harness normalization gap (no MW↔GW scaling, no K-rounding), a
fix item for the tool, not the Strategist. Misattributed: 0.

Second harness gap found: signal 3's title uses **"confirm"** (base form) —
`OVERCLAIM_TERMS` has only "confirms/confirmed", so it slipped the lexicon.

### Judge panel (3 rubric passes per signal, median)

| # | Signal | Framework claimed | Fidelity (med /3) | Falsifier (med /12) | Notes |
|---|---|---|---|---|---|
| 1 | Circle wins EU stablecoin standards battle | van de Kaa + Teece | **2** | **11** | Mechanism (regulatory exclusion → exchange installed base migrates to compliant coin) evidenced in S6/S7; "MiCA licence = complementary asset" is a doctrinally loose Teece use (it's a regulatory barrier, not a co-specialized asset), and stablecoin multi-homing weakens the lock-in premise. Falsifier is the rubric's own strong exemplar. |
| 2 | AI foundry capacity strategic bottleneck | Teece appropriability | **2** | **10** | Textbook-correct: value shifts to the scarce co-specialized asset (2nm capacity); scarcity evidenced in S3. Docked: single source; Samsung's order halt may be firm-specific (yield), generalized to the industry; "confirmed transition to early-adopters" not in the cited source → **overclaim (2/3 judges)**. Falsifier: no calendar deadline (rolling "<12 months"); >50% capacity jump in 12 months is near-infeasible → weak non-triviality. |
| 3 | Chinese EV OEMs confirm chasm crossing | Rogers/Moore diffusion | **1** | **11** | **MISAPPLICATION (2/3 judges) — post-hoc.** See adjudication below. Overclaim (2/3): "confirm" with volume-only evidence. Falsifier is dated/thresholded/checkable but only weakly refuting (a demand dip doesn't un-cross a chasm). |
| 4 | Solar+storage dominant design locks in | Utterback–Abernathy | **1** | **10** | **MISAPPLICATION (2/3 judges) — declared off 2 data points.** See adjudication below. Falsifier partially orthogonal: 100 MW of perovskite wouldn't refute the solar+*storage pairing* lock-in (perovskite plants would pair with storage too). |
| 5 | BNPL regulation forces cost pass-through | Market-failure regulation | **2** | **12** | Right lens; both preconditions in sources (S5 FCA rule July 15; S4 Klarna +40–60 bps July 1). Docked from 3: S4 never attributes the fee hike to the regulation (causality inferred), and "smaller players margin-squeezed" is asserted (S4 evidences small *merchants* penalized, not small providers). Falsifier is the rubric's second strong exemplar — auto-resolvable. |

**Panel aggregates:** theory fidelity mean **1.6/3** (Amber band 1.5–2.3);
misapplications: **2** (signals 3, 4); falsifier mean **10.8/12**, none missing,
none majority-scored non-refuting; panel overclaim rate **40%** (signals 2, 3).

### Adjudication of the Phase 2 council's three flags

**1. "Circle/Tether signal conflates installed base with complementary asset" —
REFUTED (narrowly), lesser issue confirmed.** The stored brief keeps the two
concepts distinct: the *installed base* is what transfers ("Tether's forced EEA
exit (S6) shifts installed base to Circle's MiCA-compliant USDC/EURC (S7)";
standards basis: "installed base transfer from Tether exit" — a legitimate van
de Kaa factor), while the *complementary asset* is named separately as the
licence ("Circle controls the complementary asset (regulatory approval) that
Tether lacks [T7, C3]"; "regulatory approval = scarce complementary asset in
MiCA regime"). No literal conflation. The real (milder) defect the council was
sensing: framing a regulatory authorization as a Teece complementary asset is a
stretch — it is an entry barrier, not a co-specialized asset — and two
frameworks are stapled to one event. Scored 2, not a misapplication.

**2. "Solar+storage dominant design declared off 2 data points" — CONFIRMED,
and it is worse than the council saw.** The signal cites exactly two project
announcements (S14, S15) — and S14 ("RWE and PPC complete **930 MW solar
cluster** in Greece") contains **no storage component at all**, so the claimed
"standardized solar+battery pairing" pattern rests on a single source (S15,
Rajasthan 2,450 MW + 6,400 MWh). The mot_scholar rubric's explicit fail
condition — "declaring a 'dominant design' off one deal" — applies almost
literally. No shakeout/entrant-consolidation evidence is cited. Mechanics of
the framework (competition shifts performance → cost/scale) are stated
correctly, which is why fidelity is 1, not 0. Majority misapplication.

**3. "Chinese EV chasm crossing may be post-hoc" — CONFIRMED.** All four cited
sources (S10–S13) are pure delivery-count releases (107,658; 557,090; 103,295;
30,895). Moore's precondition — pragmatists buying on value/whole-product/
infrastructure — appears nowhere in them; the adopter category is inferred from
volume alone, which the rubric requires be *evidenced, not asserted*. Declaring
the crossing "confirmed" as a Q2-2026 event in a market where BYD alone ships
557K BEVs a quarter is relabeling a transition that predates the window —
post-hoc labeling, which caps the score at 1. The dismissal of the one
contrary datapoint (S12, Li Auto −14.8%) as "product-transition noise" while
the three positives count as confirmation is confirmation-biased. Majority
misapplication + overclaim.

### Acceptance verdict per L8 target

| Target | Measured | Verdict |
|---|---|---|
| Grounding ≥95%, 0 hallucinated | raw 69.2% / adjudicated 100% traceable, **0 fabricated** | **PASS (adjudicated)** — with harness normalization fix item |
| S#/T# validity 100% | 100% (11/11) | **PASS** |
| Theory fidelity ≥2.0, 0 misapplications | mean **1.6**, **2 misapplications** (S3, S4) | **FAIL** |
| Falsifier mean ≥9/12, none missing/non-refuting | **10.8/12**, 0 missing, 0 non-refuting | **PASS** |
| Falsifier mechanical ≥3.0/4 | 3.2/4 | **PASS** |
| Overclaim ≤10% | 20% deterministic / 40% panel | **FAIL** |

**Overall: 4/6 pass. The Strategist's honesty machinery (citations, falsifiers)
is strong; its theory application overreaches** — it declares transitions
(chasm crossed, design locked) from thin or volume-only evidence and uses
"confirm(ed)" beyond what the sources support. Fix backlog: (1) prompt-side —
require adopter-category / shakeout evidence before transition declarations,
ban confirm/confirmed unless ≥2 sources evidence the mechanism; (2) harness —
MW/GW + K-rounding normalization in grounding; add base-form "confirm" (word-
boundary safe) to the overclaim lexicon; (3) re-run with a true independent
judge panel to validate the in-session medians.

## v2 prompt measurement (2026-07-02 evening)

Fresh brief judged: `strategist_briefs` row id 47, `as_of=2026-07-02`,
`focus=daily`, **generated_at 2026-07-02T17:37:38 UTC** — confirmed the
strategist-v2 output (the 11:24 v1 row was overwritten by the `as_of,focus`
upsert). 3 signals, 18 S# stories + 8 T# theory passages embedded. One
read-only Supabase SELECT; no writes; no Toqan calls.

> **Caveat — same in-session panel as the v1 judging.** Scores below are three
> independent rubric passes per signal (scholar, value-capture/preconditions
> scholar, adversarial refuter) by the evaluating model, medians taken. NOT
> three independent models — correlated-judge bias applies, and the v1 numbers
> being compared came from the same judge (which at least makes the *deltas*
> internally consistent). Treat absolutes as provisional until a true
> independent panel runs.

### Deterministic scorecard (v2 brief)

```
./venv/bin/python backend/eval/judges/strategist_eval.py --from-supabase   → exit 1
```

| Check | Result | Target | Verdict |
|---|---|---|---|
| Grounding | **100%** (2/2 hard claims: $584B→S17, 2nm→S9) | ≥95% | **PASS** — but note only 2 hard numeric claims (v1 had 13); v2 is far less evidence-dense |
| Hallucinated numbers | 0 | 0 | **PASS** |
| S#/T# validity | 100% (10/10 refs) | 100% | **PASS** |
| Falsifier mechanical | mean **2.67/4** (signals 2 & 3 have no measurable threshold) | ≥3.0, none missing | **FAIL** |
| Overclaim (lexicon) | **33.3%** (1/3: S1 "Confirmed"/"confirms", high conf but **1 source**) | ≤10% | **FAIL** |

### Judge panel (3 rubric passes per signal, median)

| # | Signal | Framework claimed | Fidelity (med /3) | Falsifier (med /12) | Notes |
|---|---|---|---|---|---|
| 1 | AI data centres cross chasm into mainstream | Rogers/Moore chasm | **0** | **9** | **MISAPPLICATION (3/3 judges)** — the exact v1 failure mode, recurred and arguably worse. Implication claims "confirmed transition from *innovators to early-adopters*" and calls that "pragmatist-ready"/"mainstream" — a category error (the chasm is visionaries→pragmatists; innovators→early-adopters is pre-chasm). The sole cited source contradicts the claim: S9's own metadata reads `adoption_stage: early-adopters`, rationale "hyperscale/AI clients are visionary adopters". Foundry capacity scarcity (supply side) is used as adopter-category evidence (demand side) — axis conflation. The brief's own watch list admits the stage transition is "currently pending … confirmation", an unaddressed internal contradiction. **Overclaim (3/3)**: "Confirmed"/"confirms" on 1 source — the precise pattern the v2 calibrated-language ban (≥2 corroborating sources) prohibits. Falsifier is dated with a baseline threshold but only weakly refuting (a spending dip doesn't un-cross a chasm) and near-formality given current momentum. |
| 2 | Capacity crunch concentrates market power in advanced nodes | Market-structure shift (Teece-flavoured scarcity/appropriability) | **2** | **9** | The worked-example style shows here: mechanism named (constraint → concentration → premium pricing), preconditions evidenced across **3 corroborating sources** (S9 order cap, S18 CoWoS-L design cancellation, S17 $584B response), and the contradicting evidence (that $584B *adds* capacity) is addressed via the falsifier and the bull scenario. v1's "may be Samsung-specific yield" refutation no longer bites — S18 shows the constraint is industry-wide. Docked from 3: lens is generic rather than a named MOT framework. Falsifier has a window ("through 2027") but no numeric threshold ("faster than AI demand grows"). |
| 3 | KRAS inhibitor discontinuity | Anderson–Tushman new S-curve | **2** | **11** | Calibrated where signal 1 is not: "potentially", "if approved", confidence=medium matching the single source. Value capture correct (patent = tight appropriability regime; first-gen displacement risk). Docked: "discontinuity / new S-curve" is loose for a same-class (G12C) next-generation molecule, and action_rationale's "superior *mechanism*" is not in S1 (superior *efficacy* is — same mechanism class). Refuter flagged the label; no majority misapplication. Falsifier (FDA rejection OR competitor equivalence by Q2 2027) is specific, dated, refuting, checkable; lacks only a numeric threshold. |

**Panel aggregates:** theory fidelity mean **1.33/3** (Red band <1.5);
misapplications: **1** (signal 1); falsifier mean **9.67/12**, none missing,
none majority non-refuting; panel overclaim rate **33%** (signal 1, 3/3 judges).

### v1 → v2 delta table

| Metric | v1 (11:24, 5 signals) | v2 (17:37, 3 signals) | Delta |
|---|---|---|---|
| Grounding (raw) | 69.2% → 100% adjudicated | **100% raw** (0 flags, 0 adjudication needed) | ✅ improved — though on 2 hard claims vs v1's 13 (v2 cites far fewer numbers) |
| Hallucinated numbers | 0 (after audit) | 0 (no audit needed) | = |
| S#/T# validity | 100% | 100% | = |
| Falsifier mechanical | 3.2/4 | **2.67/4** | ❌ regressed (2 of 3 falsifiers threshold-free) |
| Falsifier panel (/12) | 10.8 | **9.67** | ⬇ slightly (still ≥9 target) |
| Theory fidelity (/3) | 1.6 (Amber) | **1.33 (Red)** | ❌ regressed on the mean |
| Misapplications | 2 of 5 (40% of signals) | **1 of 3** (33%) | count halved; rate ~flat; the surviving one is the same chasm failure mode |
| Overclaim — deterministic | 20% (1/5) | **33.3%** (1/3) | ❌ regressed (small-N: 1 bad signal = 33%) |
| Overclaim — panel | 40% (2/5) | **33.3%** (1/3) | ⬇ marginal |
| Signal count / sparse-pack | 5 (incl. two padded misapplications) | **3** — did not pad to 5 | ✅ rule respected; notably **declined to rebuild the EV-delivery chasm signal** although S4/S12/S13/S14 (BYD 557K, NIO 107K, XPeng 103K) sat in the pack |
| Worked-example style | mixed | signal 2 fully (mechanism + evidenced preconditions + contradiction addressed); signal 3 partially; signal 1 not at all | partial adoption |
| Theory citations | inline T7 etc. | zero T# cited — defensible, since all 8 retrieved passages are generic Tesla/Schilling chapters irrelevant to the lenses used | retrieval gap, not a brief defect |

### Acceptance verdict per target (v2)

| Target | v1 | v2 | Verdict |
|---|---|---|---|
| Theory fidelity ≥2.0, 0 misapplications | 1.6, 2 misapps | **1.33, 1 misapp** | **FAIL** (mean worse, misapp count better) |
| Overclaim ≤10% | 20% det / 40% panel | **33% det / 33% panel** | **FAIL** |
| Grounding ≥95%, 0 hallucinated | pass only after adjudication | **100% raw, 0 flags** | **PASS** |
| Falsifier ≥9/12, none missing/non-refuting | 10.8 | **9.67**, 0 missing, 0 non-refuting | **PASS** (mechanical sub-target 2.67/4 **FAIL**) |

**Overall verdict: v2 did NOT beat v1 — 2/4 targets pass, same as v1's
effective standing, and the headline v1 failure mode recurred as v2's lead
signal.** The chasm-crossing signal violates every rule the v2 rewrite added:
"confirmed" on 1 source (calibrated-language ban), pragmatist preconditions
asserted not evidenced (evidence-before-labels), and its own watch-list
contradiction unaddressed. What *did* work: the sparse-pack rule (3 signals,
no padding, and the EV delivery-count bait that produced v1's worst
misapplication was left alone), raw grounding is now clean without
adjudication, and signal 2 is the first signal to fully exhibit the
worked-example shape. Interpretation caveats: with 3 signals every rate metric
moves in 33% steps, and the fidelity mean dropped partly *because* the two
padded v1 signals (scored 1) were replaced by fewer, more polarized signals
(0/2/2). Fix backlog: (1) the chasm rule needs to be example-specific — v2's
generic "evidence-before-labels" text did not stop an adopter-category
mislabel that the cited source's own stage field contradicts; consider a
hard rule: no diffusion-stage transition may be declared unless a cited
source's `adoption_stage` supports the claimed stage; (2) falsifier prompt:
require a numeric threshold, not just a comparator; (3) same harness fix items
as v1 (base-form "confirm", MW/GW) remain open; (4) re-judge with a true
independent panel — both measurements share one in-session judge.
