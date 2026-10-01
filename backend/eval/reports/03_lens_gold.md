# L3 — Gold-set expansion: model-assisted triage of the 200 seeded labels

**Purpose.** `backend/eval/gold_labels.seed.jsonl` carries the MOT lens's *own* guessed labels
(`maturity_stage`, `adoption_stage`, `business_impact`, `scope`). The gold set exists to
**grade** the lens, so rubber-stamping those guesses would make the eval circular. This pass
is a skeptical, doctrine-based review of every row so a human can verify ≥150 labels in one
focused session by triaging the flagged rows first.

**Doctrine applied** (from `docs/MOT_Framework_Library.md`, `backend/Agents_prompt/MOT_Lens_Agent.md`,
`analytics/lens.py`, `home_news/parser.py`):
- Maturity = the technology's S-curve position; adoption = the market's Rogers/Moore
  category. **Separate axes.**
- Step 1: a pure policy / macro / geopolitics / corporate-finance story with no specific
  technology → `maturity=n/a`, `adoption=n/a`.
- Funding/capex informs *maturity* (often growth), and rarely moves *adoption* past
  early-adopters. A regulatory approval is a **gate, not a stage**. A splashy launch ≠ mature.
- `business_impact`: material = re-prices the stock (M&A, approval, large funding/PPA,
  pivotal readout, binding regulation); contextual = backdrop; none = no company consequence.
- `scope`: single-company / deal (M&A, licensing, partnership) / sector (industry trend) /
  regulatory (policy/agency action) / comparison (ranking).

**Output.** `backend/eval/gold_labels.triage.jsonl` — one line per row
`{url, feed, verdict, proposed, rationale}`, covering all 200 URLs in seed order. `proposed`
lists **only** the fields I'd change (validated against `backend/eval/gold.py`'s ALLOWED vocab; every
proposed value differs from the seed value). I did **not** touch `gold_labels.jsonl` or
`gold_labels.seed.jsonl`.

---

## 1. Verdict counts

| Verdict | Rows | Share |
|---|---:|---:|
| AGREE | 164 | 82% |
| DISAGREE | 35 | 17.5% |
| INSUFFICIENT | 1 | 0.5% |
| **Total** | **200** | |

INSUFFICIENT is rare because the seeded `_title`/`_summary` are unusually rich — good news for
the gold set: nearly every row is judgeable from text without fetching the source.

## 2. Disagreement rate per field

| Field | Rows changed | of 200 |
|---|---:|---:|
| `maturity_stage` | 27 | 13.5% |
| `adoption_stage` | 11 | 5.5% |
| `scope` | 4 | 2.0% |
| `business_impact` | 2 | 1.0% |

**Maturity is by far the weakest field** — the lens's main failure mode. `business_impact`
and `scope` are largely trustworthy.

## 3. Disagreement rate per feed (DISAGREE + INSUFFICIENT)

| Feed | Non-agree / total | Rate |
|---|---:|---:|
| disruption | 11/25 | 44% |
| ev | 6/22 | 27% |
| biotech | 4/19 | 21% |
| ai-energy | 4/25 | 16% |
| fintech | 3/19 | 16% |
| geopolitics | 1/7 | 14% |
| climate | 3/23 | 13% |
| software | 2/18 | 11% |
| chips | 2/25 | 8% |
| defense | 0/17 | 0% |

`disruption` is the danger zone: it is packed with IPOs, mega-funding rounds, and frontier
deep-tech (fusion, humanoids, quantum), which is exactly where the lens over-stages. `defense`
is clean (routine procurement contracts the lens handles well).

## 4. Systematic error patterns in the lens's guesses

1. **Corporate-finance events get a fabricated tech stage instead of `n/a`.** IPOs, DRHP
   filings, earnings, recalls, cyber-breaches, and sanctions have no technology on an S-curve,
   yet the lens assigns `growth`/`dominant-design`/`mature`. Rows: 11, 16, 42, 56, 63, 64, 75,
   87, 92, 119, 166, 195 (and the SpaceX-IPO trio 11/13/64 disagree *with each other*).
2. **First-of-kind / pre-scale tech over-staged to `growth`.** "First commercial plant",
   "first cross-border network", humanoid/hydrogen build-outs are labelled `growth` when
   doctrine's emerging→growth test (mass production / accelerating volumes) is not met. Rows:
   27, 110, 151, 188, 199.
3. **Renewables mislabelled `mature`.** Solar and onshore wind are booming *dominant designs*,
   not saturated/declining `mature` technologies. Rows: 5, 28, 105.
4. **Adoption pushed past the chasm on funding or a single approval.** A big round or a
   fresh first-of-kind FDA clearance is called `early-majority`, violating the explicit
   "funding/approval ≠ crossing" rule. Rows: 12, 32, 88, 136, 188.
5. **Maturity–adoption axis confusion on capex/supply news.** Factory conversions and
   cell-supply contracts get an `adoption` stage when there is no market-uptake signal
   (should be `n/a`). Rows: 53, 182.
6. **Trials staged inconsistently (research vs emerging).** Doctrine files "trial, no product
   to buy yet" under `research`; the lens sometimes uses `emerging`. Rows: 126, 165.
7. **"Study/analysis" rows staged as a technology.** A research finding is `research`/`n/a`,
   not `growth`. Row: 187.
8. **Funding rounds mis-scoped as `deal`.** A VC/primary raise is `single-company`, not an
   M&A/partnership `deal`. Rows: 15, 151, 166.
9. **Duplicate/near-duplicate rows carry inconsistent labels — a built-in cross-check.**
   Same-event pairs the lens labelled differently: 9↔59 (ASHRAE framework), 5↔62↔105 (Meta–RWE
   PPA), 11↔13↔64 (SpaceX IPO), 41↔91 (CrowdStrike Q1), 44↔136 (KOHO raise), 67↔190 (Xcimer
   fusion), 110↔153 (Twelve SAF plant), 104↔183 (Stellantis solid-state), 151↔188 (NEURA),
   156↔193 (Nvidia–SK hynix). I resolved each toward the more doctrine-defensible label.

## 5. Top ~20 rows most needing human attention

Priority = multi-field changes, systematic-pattern anchors, and duplicate reconciliations.
(Index = 0-based line in the seed file.)

| # | Feed | Issue | Proposed |
|---|---|---|---|
| 195 | chips | INSUFFICIENT — CEO "partner" remark, no tech event | n/a or drop |
| 5 | ai-energy | solar mislabelled mature; PPA impact | maturity→dominant-design, impact→material |
| 16 | disruption | IPO filing staged | maturity→n/a, adoption→n/a |
| 59 | ai-energy | reconcile w/ row 9 (framework) | maturity→growth, adoption→early-majority |
| 64 | disruption | SpaceX IPO staged | maturity→n/a, adoption→n/a |
| 92 | fintech | Razorpay DRHP filing staged | maturity→n/a, adoption→n/a |
| 151 | disruption | humanoid over-staged; raise mis-scoped | maturity→emerging, scope→single-company |
| 166 | biotech | biotech IPO staged + mis-scoped | maturity→n/a, scope→single-company |
| 188 | disruption | humanoid over-staged both axes | maturity→emerging, adoption→early-adopters |
| 190 | disruption | fusion over-staged; impact | maturity→research, impact→contextual |
| 11 | disruption | SpaceX IPO → dominant-design | maturity→n/a |
| 42 | fintech | M&A → dominant-design | maturity→n/a |
| 68 | disruption | AI compute called "mature" | maturity→growth |
| 110 | disruption | "first SAF plant" as growth | maturity→emerging |
| 145 | ev | hands-free driving as dominant-design | maturity→growth |
| 199 | climate | green hydrogen as growth | maturity→emerging |
| 12 | disruption | funding round crosses chasm | adoption→early-adopters |
| 32 | biotech | fresh approval = early-majority | adoption→early-adopters |
| 136 | fintech | neobank raise = early-majority | adoption→early-adopters |
| 28 | climate | wind called "mature" | maturity→dominant-design |
| 87 | software | breach staged as mature | maturity→n/a |

## 6. Recommended human workflow (fastest path to ≥150 verified)

1. **Review the 36 non-AGREE rows first** (35 DISAGREE + 1 INSUFFICIENT). Each carries a
   proposed field-level correction and a one-line rationale, so this is accept/adjust, not
   re-label. Budget ~45–60 min. Verifying these gives 36 confident labels.
2. **Resolve the 10 duplicate pairs/triples together** (pattern 9). Deciding one canonical
   label per event settles both rows at once and is a strong internal consistency check.
3. **Spot-check AGREE rows by feed, worst-first.** Sample ~20% of `disruption`/`ev`/`biotech`
   AGREEs (highest disagreement feeds) and ~10% of `defense`/`chips` (cleanest). At those
   sampling rates you confirm ~130 AGREE rows.
4. **Result:** 36 triaged + ~130 sampled-and-confirmed ≈ **165 human-verified labels** in one
   session — clearing the ≥150 target from `00_baseline.md`. Any AGREE row not sampled can
   still be admitted (it passed the skeptical pass) or left for a later round.
5. **When in doubt, prefer `n/a` for corporate-finance events and the *earlier* stage at a
   genuine boundary** — matching the doctrine's debias rules and the two dominant lens errors
   above.

Deliverables written: this report and `backend/eval/gold_labels.triage.jsonl` (200 rows, validated:
parses, full URL coverage in seed order, all proposed values in-vocab). `gold_labels.jsonl`
and `gold_labels.seed.jsonl` untouched.

---

## Live scoring + A/B results (2026-07-02, PROVISIONAL gold) — EXECUTED

Gold: `backend/eval/gold_labels.provisional.jsonl` (199 rows = seed + 35 triage corrections,
1 insufficient row dropped). **PROVISIONAL — human sign-off on the 36 disputed rows
pending**; treat verdicts as directional. 146/199 rows joined (53 aged out of the
read window). Full outputs: `live_scorecard_provisional_20260702.txt`,
`lens_ab_provisional_20260702.txt`. The A/B made 19 batched Toqan calls (in-memory
classification, nothing written back).

### Per-field accuracy vs pre-committed targets (n=146, Wilson 95% CI)

| Field | Exact | 95% CI | Target | Within-1 | Target | Verdict |
|---|---|---|---|---|---|---|
| maturity_stage | **69.2%** | 61.3–76.1% | ≥70% | **82.9%** | ≥90% | exact MARGINAL FAIL · within-1 FAIL |
| adoption_stage | **71.9%** | 64.1–78.6% | ≥65% | **86.3%** | ≥90% | exact PASS · within-1 FAIL |
| business_impact | **94.5%** | 89.6–97.2% | ≥80% | — | — | PASS |
| scope | **95.9%** | 91.3–98.1% | ≥80% | — | — | PASS |

### Error profile (the target was ≥80% of stage errors adjacent)

- **Maturity:** of 45 errors, 25 are stage↔stage and **80% of those are adjacent**
  (target met on that reading) — but **20/45 (44%) involve `n/a`** (a real stage
  fabricated for an n/a item, or an n/a assigned where a stage belongs). The
  dominant failure mode is not wild stage misses; it is the **n/a boundary**,
  exactly matching the triage's top pattern (corporate-finance events given
  fabricated stages).
- **Adoption:** of 41 errors, 22 are stage↔stage and 95% of those are adjacent
  (mostly early-majority ↔ early-adopters — the chasm boundary); 19/41 involve n/a.

### A/B: stored labels (v1) vs freshly deployed prompt (v2)

| Field | v1 stored | v2 fresh | Δ |
|---|---|---|---|
| maturity_stage | **68.5%** | 63.0% | **−5.5 pp** |
| adoption_stage | **70.5%** | 63.7% | **−6.8 pp** |

**The deployed prompt scores worse than the stored history on both axes.** Caveat:
not a pure prompt-vs-prompt comparison — stored labels benefit from reconciliation
over multiple snapshots, while v2 classifies each article once. Even so, there is
no evidence the current prompt beats what's in the DB; a prompt revision (the L1
rewrite suggestions + the n/a gate) should be A/B'd with this exact tool before
deployment, and this baseline is the number a Fable 5 lens upgrade must beat:
**maturity 63.0% / adoption 63.7% single-shot, 68.5%/70.5% reconciled.**

### Acceptance verdict (provisional)

Impact/scope comfortably PASS. Maturity misses the exact bar by 0.8pp (inside the
CI) and both stage axes miss the within-1 bar — driven by the n/a boundary, which
is a promptable rule ("corporate-finance events → n/a"), not a capability wall.
The Phase 2 backlog item 3 (gate the lens) is now quantified: fixing the n/a class
alone would lift maturity exact to ~83% ceiling (121/146) if all n/a confusions
resolved.
