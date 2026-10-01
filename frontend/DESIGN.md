# Lodestar design foundation (Phase A)

The contract every Phase B tab agent builds against. Three artifacts:

- **Tokens** — `src/index.css` (`@theme` + `.dark` scaffold)
- **Primitives** — `src/components/viz.tsx` (plain SVG, presentational, typed)
- **This spec** — palette, form mapping, density rules, self-check list

Method: the dataviz skill (six-checks color formula, mark specs, interaction
rules). Every palette below was **validated by the script, not eyeballed** —
verbatim outputs at the end of §1.

---

## 1. Color system

All colors ship as CSS custom properties. **Charts reference tokens
(`var(--color-…)`), never raw hex** — the `.dark` block re-steps every slot,
so token-driven charts get dark mode for free when a toggle lands.

### 1.1 Categorical — identity ("which series")

**Fixed order. Assign slots 1..N in sequence. Never cycle, never generate a
9th hue, never repaint on refilter.** Slot 1 is the brand indigo, remaining
hues harmonized from the validated reference palette.

| Slot | Hue    | Token           | Light     | Dark      |
|------|--------|-----------------|-----------|-----------|
| 1    | blue   | `--color-cat-1` | `#3a5cd0` | `#6383e6` |
| 2    | teal   | `--color-cat-2` | `#1baf7a` | `#1baf7a` |
| 3    | amber  | `--color-cat-3` | `#eda100` | `#c98500` |
| 4    | green  | `--color-cat-4` | `#008300` | `#00993d` |
| 5    | violet | `--color-cat-5` | `#9a7ee0` | `#9085e9` |
| 6    | red    | `--color-cat-6` | `#e34948` | `#e66767` |
| 7    | magenta| `--color-cat-7` | `#e87ba4` | `#d55181` |
| 8    | orange | `--color-cat-8` | `#f2814a` | `#e06a36` |
| 9+   | —      | `--color-cat-other` | `#9499a3` | `#6f7683` — fold into "Other" |

- In `viz.tsx`: `CATEGORICAL[i]`, `seriesColor(i)`.
- **Color follows the entity, not its rank**: call
  `registerEntities(allEntities)` once with the *unfiltered* list, then
  `entityColor(name)` everywhere. Filtering never repaints survivors.
- Contrast relief (validator WARN, light mode): slots 2, 3, 7, 8 sit below
  3:1 on white. **Not dismissable** — any chart using them must ship visible
  direct labels or the ChartFrame table view. `HBarList` (direct value
  labels) and `ChartFrame table={…}` satisfy this by construction.
- Series-count ladder: 1–3 comfortable · 4 = direct labels mandatory ·
  5–6 legend/small-multiples · 7–8 ceiling · 9+ fold into "Other".
- **Dark-mode scatter caveat**: the dark set passes *adjacent* pairs
  (bars/stacks/lines) but blue↔violet collapses under protanopia when *any*
  two marks can neighbor (`--pairs all`). Dark scatter/bubble surfaces must
  keep ≤ 4 series drawn from slots 1–4 (or 1,3,4,6) **and** carry the 2px
  surface ring + legend + tooltip.

### 1.2 Sequential — magnitude ("how much")

One hue (brand indigo), light→dark, OKLCH-monotone. Dark mode **flips the
anchor**: step 100 recedes toward the dark surface.

| Step | Token | Light | Dark |
|------|-------|-------|------|
| 100 | `--color-seq-100` | `#d1defd` | `#202c4c` |
| 200 | `--color-seq-200` | `#b5cafd` | `#283a6c` |
| 300 | `--color-seq-300` | `#98b2f5` | `#324889` |
| 400 | `--color-seq-400` | `#7c9bec` | `#3d58a6` |
| 500 | `--color-seq-500` | `#5f80dd` | `#4968c2` |
| 600 | `--color-seq-600` | `#4767c8` | `#5b7ddc` |
| 650 | `--color-seq-650` | `#334faa` | `#7294ee` |
| 700 | `--color-seq-700` | `#233a89` | `#8cabfa` |

- In `viz.tsx`: `SEQUENTIAL`, `seqColor(t)` for t ∈ [0,1]. `MatrixHeat` uses it.
- **Ordinal** use (funnel stages, tiers, S-curve maturity buckets — discrete
  *ordered* marks): light mode starts at **seq-300** (light end ≥ 2:1);
  dark mode uses **seq-400 / seq-600 / seq-700** (validated `--ordinal`).
- A second simultaneous sequential context takes teal (slot 2's hue) as its
  own one-hue ramp — never a rainbow.

### 1.3 Diverging — polarity ("which side of the baseline")

Two opposing hues + a **neutral gray midpoint** (never a hue at the middle).

| Role | Token | Light | Dark |
|------|-------|-------|------|
| positive pole | `--color-div-pos` / `-soft` | `#3a5cd0` / `#b5cafd` | `#6383e6` / `#283a6c` |
| midpoint | `--color-div-mid` | `#eef0f3` | `#262a33` |
| negative pole | `--color-div-neg` / `-soft` | `#d23f3f` / `#f3b3b3` | `#e25b5b` / `#542626` |

For above/below-baseline bars, Δ-to-target, Likert/sentiment stacks centered
on neutral. When a diverging series *means* good/bad (rising = good), use
status tokens instead — never both in one chart.

### 1.4 Status — reserved state (good → critical)

Deliberately distinct steps from the categorical slots; **never used as
"series N"; always paired with an icon + label** (never color alone).
Seeded from the app's existing `--color-up`/`--color-down` semantics.

| Role | Token | Light (contrast on #fff) | Dark (contrast on #171a21) |
|------|-------|--------------------------|----------------------------|
| good | `--color-status-good` / `-soft` | `#18895a` (4.41) | `#34c383` (7.69) |
| warning | `--color-status-warning` / `-soft` | `#a9791f` (3.86) | `#d9a13c` (7.56) |
| serious | `--color-status-serious` / `-soft` | `#c2410c` (5.18) | `#e8703d` (5.65) |
| critical | `--color-status-critical` / `-soft` | `#b42328` (6.54) | `#e25b5b` (4.88) |

`StatTile`'s delta chip computes good/bad as *direction × whether up is
good* and wears these tokens. Existing `--color-up/-down/-warn` stay valid
for text semantics; new chart code prefers the status tokens.

### 1.5 Chart chrome & ink

**Text wears text tokens, never a series color.** Values, labels, legends,
axis text: ink tokens; a colored mark *beside* the text carries identity.

| Role | Token | Light | Dark |
|------|-------|-------|------|
| primary ink | `--color-chart-ink` | `#16181d` | `#e8eaf0` |
| secondary ink | `--color-chart-ink-2` | `#5f636c` | `#b3b9c6` |
| axis/tick labels | `--color-chart-label` | `#9499a3` | `#7e8694` |
| gridline (hairline, solid) | `--color-chart-grid` | `#f1f2f5` | `#232733` |
| baseline / axis rule | `--color-chart-axis` | `#e2e3e8` | `#2e3342` |
| chart surface | `--color-surface` | `#ffffff` | `#171a21` |

### 1.6 Dark scheme scaffold

`.dark` on `<html>` activates it (class strategy — Tailwind v4 utilities
read the vars at runtime; no toggle ships yet). Every core UI token
(`canvas`, `surface`, `ink…`, `brand…`, `up/down/warn…`) and every viz token
has a dark value. Dark categorical/sequential values are **selected steps
re-validated against `#171a21`**, not an automatic flip.

### 1.7 Validator output (verbatim)

`node scripts/validate_palette.js` from the dataviz skill:

```
== LIGHT adjacent ==
Palette (light, surface #ffffff, categorical): 8 slots
  [PASS] Lightness band         all 8 inside L 0.43–0.77
  [PASS] Chroma floor           all 8 >= 0.1
  [PASS] CVD separation         worst adjacent #008300↔#eda100 ΔE 24.2 (protan) · tritan 12.1 · normal 41.1
  [WARN] Contrast vs surface    below 3:1 — relief required (visible labels or table view): [["#1baf7a",2.82],["#eda100",2.17],["#e87ba4",2.69],["#f2814a",2.62]]
  → ALL CHECKS PASS  (CVD in the 8–12 floor band is legal ONLY with secondary encoding: direct labels, gaps, or texture)

== LIGHT all-pairs ==
Palette (light, surface #ffffff, categorical): 8 slots
  [PASS] Lightness band         all 8 inside L 0.43–0.77
  [PASS] Chroma floor           all 8 >= 0.1
  [PASS] CVD separation         worst all-pairs #e87ba4↔#1baf7a ΔE 12.9 (deutan) · tritan 12.1 · normal 24.1
  [WARN] Contrast vs surface    below 3:1 — relief required (visible labels or table view): [["#1baf7a",2.82],["#eda100",2.17],["#e87ba4",2.69],["#f2814a",2.62]]
  → ALL CHECKS PASS

== DARK adjacent ==
Palette (dark, surface #171a21, categorical): 8 slots
  [PASS] Lightness band         all 8 inside L 0.48–0.67
  [PASS] Chroma floor           all 8 >= 0.1
  [PASS] CVD separation         worst adjacent #00993d↔#c98500 ΔE 14.7 (protan) · tritan 7.9 · normal 25.4
  [PASS] Contrast vs surface    all 8 >= 3:1
  → ALL CHECKS PASS

== DARK all-pairs ==
Palette (dark, surface #171a21, categorical): 8 slots
  [PASS] Lightness band         all 8 inside L 0.48–0.67
  [PASS] Chroma floor           all 8 >= 0.1
  [FAIL] CVD separation         worst all-pairs #9085e9↔#6383e6 ΔE 3.1 (protan) · tritan 4.1 · normal 11.6
  [PASS] Contrast vs surface    all 8 >= 3:1
  → FAILED — fix the marked checks
```

Notes on the two flagged rows:

- **Light contrast WARN** → relief rule, enforced by construction: direct
  value labels (`HBarList`) or the `ChartFrame` table view. Never ship a
  sub-3:1 fill with neither.
- **Dark all-pairs FAIL** (blue↔violet under protanopia) applies only to
  chart types where any two marks can neighbor (scatter/bubble/map). The
  dark *adjacent* set — what stacks, bars, and multi-line use — is a full
  PASS at ΔE 14.7 (above the ≥ 12 target; the skill's own reference dark
  palette sits at 10.3). Rule recorded in §1.1: dark scatter keeps ≤ 4
  series from slots {1,3,4,6} with rings + legend + tooltip.

Ordinal sub-ramps (validated `--ordinal`):

```
light seq-300…700: monotone ✓ · ΔL ≥ 0.06 ✓ · light end 2.10:1 ✓ · single hue ✓  → ALL CHECKS PASS
dark  seq-400/600/700: monotone ✓ · ΔL ≥ 0.06 ✓ · light end 2.61:1 ✓ · single hue ✓ → ALL CHECKS PASS
```

---

## 2. Primitives — when to use which

All in `src/components/viz.tsx`. Plain SVG, no chart library, dumb/
presentational (data via props), `cn()` for class merging. `charts.tsx`
(recharts) keeps working as-is; Phase B migrates page-by-page onto these.

| Primitive | The data's job | Lodestar examples |
|---|---|---|
| `StatTile` | a single current value (+ delta, + trend) | KPI rows on every tab: tracked cap, move counts, hit-rate, coverage |
| `HBarList` | compare magnitude across named categories | momentum leaderboard (± from zero), share-of-voice (with drift `chip`s), intensity top-N, concentration, co-mentions, reactions |
| `TimeSeries` (line) | trend over time, distinct series | sentiment pos/neg/neutral, benchmark curves, price series |
| `TimeSeries` (area) | part-to-whole trend over time | volume by feed (stacked) |
| `MatrixHeat` | magnitude on a grid | MOT strategic-move matrix, co-mention matrix |
| `ChartFrame` | the card anatomy around ALL of the above | every chart card |
| `Legend`, `Tooltip` | shared identity + readout | composed automatically by the above; exported for custom charts (S-curve, chord) |

Mapping decisions the form heuristic forces:

- **One headline number is never a one-bar chart** — `StatTile`.
- Momentum (±%) → `HBarList` with `color` per datum from **diverging or
  status** tokens (it means better/worse), not categorical.
- Share-of-voice → `HBarList`, slot-1 single hue for all bars (nominal
  categories never get a value-ramp or per-bar hues), drift as a `chip`
  (Badge) per row — the chip wears status tokens.
- Market-cap share (currently a donut) → horizontal stacked bar or
  `HBarList`; donut only for at-a-glance part-to-whole with ≤ 6 segments.
- Sentiment → `TimeSeries` line; positive/negative *mean* good/bad → status
  good/critical + `--color-flat` for neutral, not categorical.
- "One tech went up, rest are context" → **emphasis**: the one series in
  brand, the rest `--color-cat-other`; not 8 hues.
- \> ~7 meaningful classes → a table (ChartFrame's table view *is* the chart).
- **Never a dual y-axis.** Two measures of different scale = two charts or
  index both to 100 at t0. The `TimeSeries` API has no second axis on purpose.

Baked-in mark specs (don't undo them): bars ≤ 24px, 4px rounded data-end,
square baseline; 2px lines, round caps; markers r4 + 2px surface ring; 2px
surface gaps in stacks; hairline solid grid; hover layer + keyboard focus
everywhere; hit targets ≥ the full row/24px, never just painted pixels.

---

## 3. Density & card anatomy (Phase B rules)

Every chart card follows **one anatomy** — `ChartFrame` renders it:

1. **Title** — what this is, 3–6 words.
2. **Read line** — *one sentence* saying what the chart **says** ("Robotics
   is heating up while consumer AI cools"), not what it shows. This is the
   hero of the card; a reader who reads only read-lines gets the briefing.
3. **Viz** — the primitive.
4. **Caption** — provenance/window ("30d, n=412 items"), muted, optional.

Density rules:

- **Max ~5 visible rows**, then fold behind "Show all N"
  (`HBarList collapsedAfter={5}`; use the same pattern for lists/tables).
- **Text walls → progressive disclosure**: agent summaries and long reads
  get one visible sentence (the read line) + an expander for the rest.
  `Insight`/expander from `ui.tsx`, never a full-width paragraph block.
- **One hero figure per view** (≥ 48px); KPI rows of `StatTile` for the
  handful of headline numbers; everything else is a chart or a table.
- **Filters in one row above the charts** they scope — never inside a card,
  never per-chart. On refetch hold the previous render at reduced opacity;
  no skeleton flash, no layout jump.
- Tables/axis ticks use `.num` (tabular); hero/StatTile values stay
  proportional.
- Container heights include the x-axis band, or grow with content — no
  nested scrollbars inside cards.

---

## 4. Anti-pattern self-check (every tab agent, every chart)

Before shipping a card, check each line — a "yes" means fix it:

- [ ] Two y-scales on one plot? (→ two charts or index to 100)
- [ ] Colors assigned by current rank / repainted after a filter? (→ `entityColor`)
- [ ] A 9th generated hue, or hues cycled? (→ "Other", small multiples)
- [ ] Bars colored darker-where-bigger on nominal categories? (→ slot 1 for all)
- [ ] Rainbow or multi-hue ramp for magnitude? (→ sequential tokens)
- [ ] A hue (not gray) at a diverging midpoint? (→ `--color-div-mid`)
- [ ] Status color used as "series 4", or a series color used for status?
- [ ] Eight hues when the story is one number? (→ emphasis or `StatTile`)
- [ ] One-bar bar chart or 2-slice pie? (→ `StatTile`)
- [ ] A number on every point? (→ selective labels; legend + tooltip carry the rest)
- [ ] Label clipped by / overflowing its mark? (→ outside the end, or tooltip)
- [ ] Text wearing a series color? (→ ink tokens + colored key beside it)
- [ ] ≥ 2 series with no legend, or 1 series with a redundant one?
- [ ] Sub-3:1 fill (cat-2/3/7/8 on light) with no direct labels and no table view?
- [ ] Tooltip the only way to read a value? (→ labels or table view)
- [ ] Pinpoint hover targets? (→ row-height / ≥ 24px hit areas — built in)
- [ ] Dashed gridlines, borders drawn around marks, thick saturated blocks?
- [ ] Filters inside a chart card? (→ one row above)
- [ ] Skeleton flash on refetch? (→ previous render at reduced opacity)
- [ ] Hardcoded hex in a chart? (→ tokens, so dark mode keeps working)
- [ ] Dark-mode scatter with > 4 series or violet+blue together? (§1.1 caveat)
- [ ] `tabular-nums` on a hero/StatTile value? (→ proportional figures)

---

## 5. Verification record (Phase A)

- `npx tsc -b --noEmit` — clean.
- Render smoke test: all primitives mounted via `react-dom/server`
  (ChartFrame + table toggle, HBarList + expander + chips, TimeSeries line
  & stacked area, StatTile + delta + sparkline, Legend, Tooltip, MatrixHeat)
  — all assertions passed; temporary harness deleted.
- `./venv/bin/python -m pytest -q` — 446 passed (backend untouched).
- Existing pages compile unchanged against `ui.tsx` / `charts.tsx`.
