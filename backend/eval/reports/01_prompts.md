# Phase 1 — L1 Agent Prompts (offline)

Date: 2026-07-02 · Branch: `main` · Rubric: `backend/eval/rubrics/prompt_quality.md` ·
All checks offline (no Supabase/Toqan/web). Nothing in `backend/Agents_prompt/` or production
code was modified.

## 1. Verdict vs acceptance targets

| Target (from `backend/eval/reports/00_baseline.md`) | Result |
|---|---|
| **0 schema-drift mismatches** across all 13 prompts (GATE) | ✅ **MET — 0 mismatches.** Verified by hand and mechanically (`backend/eval/judges/prompt_audit.py` → exit 0). |
| Every prompt **≥ 80% (Green)**, none Red | ⚠️ **MISSED for 2 of 13.** 11 Green; **Strategist 70.8% (Amber)** and **Ask 75.0% (Amber)**. **None Red.** |

Overall: the data-integrity layer is clean — every declared field, key name, enum
value, date format, and array/object shape matches its consumer exactly. The gap to
Green on Strategist/Ask is style-lever quality (no worked examples, no version
markers, thin edge paths), not correctness — fixable with prompt-only rewrites.

Re-run the drift check any time:

```
./venv/bin/python backend/eval/judges/prompt_audit.py   # exit 0 = no drift
```

## 2. Schema-drift findings (the GATE)

### 2.1 Extractors (10) → `home_news/parser.py` — ALIGNED, 0 mismatches

Checked per prompt: declared keys, enum vocab, date format, output shape.

| Contract element | Prompts declare | Consumer expects | Match |
|---|---|---|---|
| Item keys | `title, summary, url, source_name, published_at, country, tags, companies, sentiment, business_impact, scope` (all 10 prompts, OUTPUT FORMAT block) | canonical keys resolved in `parser.py:_build_item` (192–252) / `HomeNewsItem` (59–82) | ✅ exact, no extra/missing/renamed key in any prompt |
| `sentiment` vocab | `positive \| negative \| neutral` | `parser.py:241` | ✅ all 10 |
| `business_impact` vocab | `material \| contextual \| none` | `_BUSINESS_IMPACT_VALUES` `parser.py:21` | ✅ all 10 |
| `scope` vocab | `single-company \| deal \| sector \| regulatory \| comparison` | `_SCOPE_VALUES` `parser.py:22` | ✅ all 10 (order varies; sets identical) |
| Date format | `YYYY-MM-DD` (ISO-8601) | `datetime.fromisoformat(str(raw)[:10])` `parser.py:212` | ✅ |
| Shape | "Return **only** a JSON array" | `parse_json_array` `parser.py:150` | ✅ |
| Alias bans | 8/10 prompts explicitly ban `date`/`source`/`category`/`headline`-style aliases | parser tolerates aliases but records them as `keydrift` provenance (`parser.py:104–132`) | ✅ (see obs. O2 for the 2 without the ban) |

### 2.2 MOT Lens → `analytics/lens.py` + gold vocab — ALIGNED, 0 mismatches

| Contract element | Prompt (`MOT_Lens_Agent.md`) | Consumer | Match |
|---|---|---|---|
| Object keys | `index, maturity_stage, adoption_stage, strategic_move, rationale, prompt_version` (lines 2–7) | `reconcile_batch` reads exactly these (`lens.py:83–91`; `rationale`→`lens_rationale`, `prompt_version`→`lens_prompt_version`) | ✅ |
| `maturity_stage` | `research, emerging, growth, dominant-design, mature, declining, n/a` (lines 33–39) | `_MATURITY` `lens.py:35` | ✅ 7/7 |
| `adoption_stage` | `innovators, early-adopters, early-majority, late-majority, laggards, n/a` (lines 52–57) | `_ADOPTION` `lens.py:36` | ✅ 6/6 |
| `strategic_move` | `standards-battle, entry-timing, collaboration, appropriability, platform, disruption, none` (lines 63–69) | `_MOVE` `lens.py:37` | ✅ 7/7 |
| `prompt_version` | literal `"mot-lens-v3"` (line 7) | `LENS_PROMPT_VERSION = "mot-lens-v3"` `lens.py:33` | ✅ |
| `index` base | "0-based" (line 4), any order OK | `_classify_batch` numbers items from `enumerate(rows)` = 0-based and joins by index (`lens.py:120–146`) | ✅ |
| Shape | JSON array, one object per item | `parse_json_array` + by-index lookup (`lens.py:132–146`) | ✅ |
| Gold vocab | — | `backend/eval/gold.py:26–37` **imports** `_MATURITY`/`_ADOPTION` from the lens and `_BUSINESS_IMPACT_VALUES`/`_SCOPE_VALUES` from the parser | ✅ aligned by construction |

**Who produces what (rubric question):** the four gold fields split cleanly —
`business_impact` + `scope` are produced by the **feed extractors** (validated/defaulted
in `parser.py:246–252`); `maturity_stage` + `adoption_stage` by the **MOT Lens**. The
lens prompt correctly claims neither of the parser's fields and vice-versa. No overlap,
no orphan.

### 2.3 Bonus (beyond the rubric's GATE list): Strategist → `analytics/strategist.py` — ALIGNED

Top-level keys (`bottom_line, confidence, signals, convergence, scenarios, watch`),
signal keys (all 12 incl. `standards.{leader,basis,read}`), and every enum —
`action` = `_ACTIONS` (`strategist.py:68`), `impact` = `_IMPACT` (:69), `horizon` =
`_HORIZON` (:70), `confidence` = `_CONFIDENCE` (:67) — match
`_normalize_structured` (`strategist.py:95–152`) exactly. Single-JSON-object shape
matches `parse_json_object`. Ask returns Markdown prose; there is no parser to drift
against (its `[S#]`/`[T#]` citation convention matches the pack built by
`analytics/ask.py:133–165`).

### 2.4 Observations that are NOT drift (for the record)

- **O1** — Prompt tie-break defaults (`contextual`, `single-company`) mirror the parser's
  defaults (`parser.py:25–26`). `Geopolitics_Trade_Feed_Agent.md:97` breaks ties to
  `regulatory` instead — an agent-side domain judgment, still in-vocab; not drift.
- **O2** — `AI_Energy_Impact_Feed_Agent.md` and `EV_Developments_Feed_Agent.md` are the
  only two prompts **without** the "OUTPUT CONTRACT (read first)" header and its explicit
  "exactly these keys / never `date`,`source`,`category`" ban. Their declared schema still
  matches, but they lean on the parser's keydrift tolerance, which the rubric says prompts
  should not (rewrite R6).
- **O3** — EV's "STRICTLY last 72 hours" is tighter than the parser's `max_age_days=7`
  staleness cutoff — safe direction.
- **O4** — The rubric wants the lens to return a "confidence/modal-share signal";
  `lens.py` parses **no** confidence key today, so adding one to the prompt alone would be
  silently dropped. Flagged as a coordinated prompt+code change (R7), deliberately **not**
  counted as drift.
- **O5** — Extractor `tags` vocabularies are per-feed suggestions; the parser stores tags
  as a free list (`parser.py:216–221`) — no enum to drift against.

## 3. Scoring — 13 prompts

Criteria: **U1** role clarity · **U2** schema explicit · **U3 GATE** (pass/fail) ·
**U4** grounding · **U5** boundary examples · **U6** edge/failure handling ·
**U7** determinism · **U8** versioning. Extractor-specific: **E1** strict array ·
**E2** dedup · **E3** ISO date · **E4** entity normalization · **E5** no fabricated
fields/keys · **E6** JSON-only/non-array guard. Each 0/1/2.

### 3.1 The seven "contract-template" extractors — identical scores: 22/26 = 84.6% **GREEN**

Applies to **Semiconductor (Chips), Biotech & Health, Climate & Energy, Defense & Space,
Fintech & Digital Assets, Geopolitics & Trade, Software & Cyber** (same template; evidence
line-refs are to `Semiconductor_News_Feed_Agent.md`, identical structure in the others).

| Criterion | Score | Evidence (one line) |
|---|---|---|
| U1 role clarity | 2 | "single job… not a research assistant or chatbot" (:11–13) |
| U2 schema explicit | 2 | Exact 11 keys up top (:2–3) + closed enums per field (:73–97) |
| U3 GATE | **PASS** | §2.1 — keys/enums/date/shape all match parser |
| U4 grounding | 2 | "NEVER fabricate URLs/dates/figures" (:57); cite article's own date (:55); when-unsure defaults match parser's |
| U5 boundary examples | 1 | One easy worked example (:100–114); no hard-case examples (mixed-sentiment, deal-vs-single-company) |
| U6 edge handling | 1 | JSON-only + no-prose enforced (:6, :57), but no explicit "nothing qualifies → return `[]`" path |
| U7 determinism | 2 | "pick the dominant impact; when unclear `neutral`… when unsure `contextual`/`single-company`; never blank" (:82–97) |
| U8 versioning | 0 | No version marker anywhere |
| E1 strict array | 2 | ":2 Return only a JSON array" |
| E2 dedup | 2 | "Cluster items on the same event; keep the most authoritative source" (:46) |
| E3 ISO date | 2 | "YYYY-MM-DD" (:5, :70) |
| E4 entity normalization | 2 | "Canonical brand names, max 5, `[]` if none" (:85) |
| E5 no fabricated fields | 2 | "exactly these keys and no others… never `date`, `source`, or `category`" (:2–5, self-check :119) |
| E6 non-array guard | 2 | "Output nothing but the JSON array… valid JSON, parseable as-is" (:6, :123) |
| **Total** | **22/26 = 84.6%** | **GREEN** |

Rewrites (all seven): (1) add "if nothing qualifies, return `[]`" (U6); (2) port the
long-form anti-confusion scope warning ("do NOT pick `deal`/`comparison` just because
several companies are named") + one hard worked example (U5); (3) add a version header
(U8, see R5 caution).

### 3.2 Disruptive_Tech_Feed_Agent.md — 23/26 = 88.5% **GREEN**

| Criterion | Score | Evidence |
|---|---|---|
| U1 | 2 | One-test framing: "could this change who wins in a market?" (:15) |
| U2 | 2 | Contract block (:1–8) + closed enums (:105–143) |
| U3 GATE | **PASS** | §2.1; explicitly bans the legacy `competitive_impact` key (:6, :113) |
| U4 | 2 | "NEVER fabricate…" (:84); date from article not snippet (:77) |
| U5 | 2 | Hard cases in-line: "pre-revenue lab demo is usually `none`" (:130), quoted deal example (:139), entrant-vs-incumbent sentiment (:116–120) |
| U6 | 1 | "if there are only 6 strong items, return 6" (:86) but no empty-`[]` path |
| U7 | 2 | Dominant-impact tie-breaks + reserve-`deal`/`comparison` rule (:120, :143) |
| U8 | 0 | No version marker |
| E1–E6 | 2,2,2,2,2,2 | Contract block; dedup (:65–66); ISO (:104); canonical names/max 5 (:122–127); alias + extra-key bans (:113); parseable-as-is self-check (:174) |
| **Total** | **23/26 = 88.5%** | **GREEN** — best extractor |

Rewrites: add empty-`[]` path; version header.

### 3.3 AI_Energy_Impact_Feed_Agent.md — 22/26 = 84.6% **GREEN**

| Criterion | Score | Evidence |
|---|---|---|
| U1 | 2 | "one thing: how AI consumes energy… not a general AI-news feed" (:2–4) |
| U2 | 2 | Keys + closed enums declared (:88–134) |
| U3 GATE | **PASS** | §2.1 |
| U4 | 2 | NEVER-fabricate (:77); article-date rule (:70) |
| U5 | 2 | Hard cases: "most footprint studies are `neutral`" (:110), PPA deal example (:130), industry-vs-environment sentiment split (:107) |
| U6 | 1 | "only 6 strong items, return 6" (:79); no empty-`[]` path |
| U7 | 2 | Dominant-impact + reserve-`deal`/`comparison` tie-breaks (:111, :134) |
| U8 | 0 | No version marker |
| E1 | 2 | "Return a JSON array" (:88) + "only the structured list" (:82) |
| E2 | 2 | Cluster + representative rule with worked count (:59) |
| E3 | 2 | ISO-8601 YYYY-MM-DD (:97) |
| E4 | 2 | Canonical brand, skip generics, max 5 (:114–118) |
| E5 | 1 | **No "exactly these keys/no others" or alias ban** — the only guard is the key list itself (obs. O2) |
| E6 | 2 | "valid JSON, parseable as-is, with no surrounding text" (:163) |
| **Total** | **22/26 = 84.6%** | **GREEN** |

Rewrites: add the OUTPUT CONTRACT header + alias bans (R6); empty-`[]` path; version header.

### 3.4 EV_Developments_Feed_Agent.md — 22/26 = 84.6% **GREEN**

| Criterion | Score | Evidence |
|---|---|---|
| U1 | 2 | "single job… not an investment advisor" (:2–4) |
| U2 | 2 | Keys + closed enums (:90–133) |
| U3 GATE | **PASS** | §2.1 (72h window is tighter than parser's 7-day cutoff — safe, O3) |
| U4 | 2 | NEVER-fabricate (:76); article-date rule (:70) |
| U5 | 2 | Best hard cases of any extractor: "a single car fire is `negative` sentiment but usually `none` for business impact" (:120), "Ford adopts Tesla NACS" = `deal` (:129), two-sided tariff sentiment (:110) |
| U6 | 1 | "only 6 strong items, return 6" (:78); no empty-`[]` path |
| U7 | 2 | Dominant-impact + reserve rules (:110, :133) |
| U8 | 0 | No version marker |
| E1 | 2 | "Return a JSON array" (:87) |
| E2 | 2 | Cluster rule with worked count ("4 outlets = 1 entry", :59) |
| E3 | 2 | ISO-8601 (:96) |
| E4 | 2 | Canonical brand not ticker/subsidiary, max 5 (:113–117) |
| E5 | 1 | **No exact-keys/alias ban** (obs. O2) |
| E6 | 2 | "parseable as-is, no surrounding text" (:161) |
| **Total** | **22/26 = 84.6%** | **GREEN** |

Rewrites: same as AI Energy (contract header + alias bans; empty path; version header).

### 3.5 MOT_Lens_Agent.md — 21/22 = 95.5% **GREEN** (best prompt)

Role criteria: **L1** dimensions defined with cues · **L2** single modal stage +
confidence/modal-share signal · **L3** don't-over-stage · **L4** maturity vs adoption axes.

| Criterion | Score | Evidence |
|---|---|---|
| U1 | 2 | "You are a classifier, not a writer… each item independently" (:16) |
| U2 | 2 | Six exact keys + three closed vocabs + index semantics (:2–8) |
| U3 GATE | **PASS** | §2.2 — keys, all three vocabs, `mot-lens-v3` literal, 0-based index all match `lens.py` and gold |
| U4 | 2 | "Do not search the web. Judge only from the text given" (:8); `n/a` rather than guessed middle stage (:21, :103) |
| U5 | 2 | Worked example per stage incl. the chasm and both failure directions (:83–98); adjacent-boundary tests (:41–47) |
| U6 | 2 | `n/a`/`none` no-force paths (:103); JSON-only; index maps any order (:124) |
| U7 | 2 | Ordered decision procedure (:19–27), earlier-stage tie-break scoped to genuine ties, DEBIAS section (:75–79) |
| U8 | 2 | `prompt_version: "mot-lens-v3"` echoed on every object (:7) — the attribution mechanism `lens.py:193` consumes |
| L1 dimensions + cues | 2 | Each lens defined with named frameworks and observable cues (:31–71) |
| L2 single stage + confidence signal | 1 | Single best-fit stage enforced (:103) but **no confidence/modal-share output** — and `lens.py` parses none (O4) |
| L3 don't over-stage | 2 | Both directions: "overclaiming manufactures false transitions" AND "don't under-stage an established technology" (:25, :48, :79) |
| L4 axes distinguished | 2 | "Rate maturity and adoption on SEPARATE axes… they move independently" (:23); debias bullet (:79) |
| **Total** | **21/22 = 95.5%** | **GREEN** |

Rewrites: (1) if a confidence signal is wanted, add `"confidence": high|medium|low`
per item **together with** a `lens.py:reconcile_batch` change — never prompt-only (O4);
(2) minor: state "if the input list is empty, return `[]`"; (3) minor: self-check line
131 restates the tie-break without the "unless clearly at scale" qualifier — mirror
Step 3's full wording to avoid the under-staging bias the body works hard to prevent.

### 3.6 Strategist_Agent.md — 17/24 = 70.8% **AMBER**

Role criteria: **S1** signal completeness (lens+action+impact+horizon+value-capture+
falsifier+sources+confidence) · **S2** theory correct · **S3** no assertive verbs beyond
evidence · **S4** scenarios grounded · **S5** convergence ≥2 domains.

| Criterion | Score | Evidence |
|---|---|---|
| U1 | 2 | "the app's brain… the narrowing function"; client + decision defined (:7–10) |
| U2 | 2 | Full JSON shape with closed enums for action/impact/horizon/confidence + 11-label lens vocabulary (:40–86) |
| U3 GATE | **PASS** | §2.3 — matches `strategist.py:_normalize_structured` exactly |
| U4 | 2 | "Reason only over the data pack… do not invent… reference by S#/T#" (:2); NEVER block (:93) |
| U5 | 0 | **No worked example anywhere** — no sample signal, no filled `standards` object, no CONTESTED demotion example |
| U6 | 1 | `convergence: []` if none (:86) and CONTESTED→watch-item rule (:35), but **no sparse-pack path**: ":82 signals: 3–5 items" conflicts with "skip non-decisive entirely" when <3 decisive signals exist — pad pressure |
| U7 | 2 | "pick the closest single label" (:83); deterministic ordering impact×confidence (:82); fill-rules for value_capture/standards (:84–85) |
| U8 | 0 | No version marker (`strategist_briefs` rows are not attributable to a prompt version, unlike lens rows) |
| S1 completeness | 2 | Every required element in the schema + "Every signal MUST have an action, an impact, and a falsifier" (:82, :91) |
| S2 theory correct | 2 | Doctrine matches `docs/MOT_Framework_Library.md` (S-curve/A1–A2, chasm B1–B2, Teece C3, van de Kaa C1, real options E2); the Teece "who captures value" question and standards-basis factors are stated correctly (:21, :84–85) |
| S3 claim calibration | 1 | Confidence tied to corroboration+recency and "corroborated signal vs unfalsified guess" (:25) — but no explicit assertive-verb restraint (the L8 overclaim-rate lever) |
| S4 scenarios grounded | 1 | base/bull/bear mandatory with triggers (:69–73) but no requirement to trace scenarios to `[S#]` — the one output block that may float free |
| S5 convergence ≥2 domains | 2 | `feeds` array + "genuine multi-feed overlap… never invent one" (:86, :100) |
| **Total** | **17/24 = 70.8%** | **AMBER** |

Rewrites: see R1, R2, R5 below (highest-leverage of all 13).

### 3.7 Ask_Bellwether_Agent.md — 15/20 = 75.0% **AMBER**

Role criteria: **A1** strictly from retrieved context · **A2** valid citations only ·
**A3** explicit uncertainty/refusal.

| Criterion | Score | Evidence |
|---|---|---|
| U1 | 2 | "grounded analyst, not a chatbot riffing from memory and not a web researcher" (:7) |
| U2 | 2 | Output structure fully specified for a prose agent: direct answer → grounded support → confidence line; no JSON/fences (:24–27, :2) |
| U3 GATE | **PASS** (n/a) | Prose output, no parser; `[S#]`/`[T#]` convention matches the pack `analytics/ask.py:133–165` builds |
| U4 | 2 | "Reason only over the data pack… do not invent" (:2); every claim traces to `[S#]` (:32) |
| U5 | 0 | **No worked example** — no sample Q→A, no refusal example |
| U6 | 2 | "If the pack does not contain enough to answer, say so plainly and state what's missing" (:2, :41) — the strongest refusal path of the 13 |
| U7 | 1 | "use what fits, don't force" (:9) is the only determinism cue; no guidance on length/citation-density consistency |
| U8 | 0 | No version marker |
| A1 from context only | 2 | Everything traces to pack + prior turns; web banned (:2, :34) |
| A2 valid citations only | 2 | Cites the developments **used** as `[S#]`; "nothing is fabricated" self-check (:40) — though an explicit "only ids present in the pack" ban would close the phantom-ref gap (L9 target: 0) |
| A3 uncertainty/refusal | 2 | Explicit thin-evidence and can't-answer paths (:2, :32, :41) |
| **Total** | **15/20 = 75.0%** | **AMBER** |

Rewrites: see R3, R5 below.

## 4. Ranked rewrite suggestions (input to the Fable 5 prompt upgrade)

1. **R1 — Strategist: add worked examples (U5 = 0, the single biggest deficit).** One
   filled example signal (ideally a `Standards battle` showing the `standards` object and
   a `value_capture` line), plus one example of demoting a CONTESTED transition to `watch`.
   This is the prompt whose output the L8 judges (mot_scholar, falsifier) score — examples
   directly train falsifier/lens quality.
2. **R2 — Strategist: sparse-pack + overclaim rules.** Replace ":82 signals: 3–5 items"
   with "up to 5; if fewer than 3 developments are genuinely decisive, return fewer — never
   pad", and add "use assertive verbs ('wins', 'confirms') only when ≥2 independent `[S#]`
   corroborate; otherwise hedge". Targets the L8 overclaim ≤10% metric.
3. **R3 — Ask: worked example + refusal example + phantom-citation ban.** One short Q→A
   showing the direct-answer-first shape, one "the pack can't answer this" refusal, and an
   explicit "cite only `[S#]`/`[T#]` ids that appear in the pack" (L9 target: 0 phantom
   citations).
4. **R4 — Seven condensed extractors: hard-case boundary rules + empty path.** Port the
   long-form warnings ("do NOT pick `deal`/`comparison` just because several companies are
   named"; one mixed-sentiment worked example) and add "if nothing qualifies, return `[]`".
5. **R5 — Version markers on the 12 unversioned prompts.** Only the MOT Lens carries one.
   Add a documentation header (e.g. `<!-- prompt: chips-feed-v2 -->`) to each extractor +
   Strategist + Ask. **Caution:** do NOT add a version *output field* to extractor items —
   the contract is "exactly these keys and no others" and `parser.py` stores no such
   column; a header (or a `strategist_briefs` version column, if wanted for L8 A/B) is the
   drift-free route.
6. **R6 — AI Energy + EV: add the OUTPUT CONTRACT header block** (exact keys, "never
   `date`/`source`/`category`") for parity with the other eight — today they rely on the
   parser's keydrift tolerance, which the rubric says prompts must not (O2).
7. **R7 — MOT Lens (optional, coordinated change only):** per-item `confidence` for the
   rubric's modal-share signal — requires a matching `lens.py:reconcile_batch` +
   `feed_runs` change in lockstep; prompt-only would be silently dropped (O4).

## 5. Judge artifact

`backend/eval/judges/prompt_audit.py` (new, eval-only — no production code touched) mechanically
re-extracts declared keys + enums from all 12 machine-consumed prompts and diffs them
against `parser.py` / `lens.py` / `strategist.py` (vocabs imported or AST-parsed from the
modules themselves, so the judge can't drift from the source of truth). Verified both
ways: exit 0 on the real prompts; a negative test with a mutated prompt (renamed
`published_at`→`date`, altered scope vocab) produced 4 DRIFT findings. Ask is prose-only
and intentionally skipped.

## 6. Proposed live steps

**None.** L1 is fully checkable offline; all checks above ran offline.
