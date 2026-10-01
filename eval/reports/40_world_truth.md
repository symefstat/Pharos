# World-Truth Benchmark — MOT Analyst placements vs reality (2026-07-02)

**Question answered:** are the S-curve/diffusion placements claims about *today's
world*, or about *today's news*? Method: 10 independent research agents, 2
technologies each, web-sourced evidence (production volumes, market share,
standards outcomes, buyer behavior — sources cited in agent outputs), judged
against the lens's own stage definitions and boundary tests
(`Agents_prompt/MOT_Lens_Agent.md`). App placements from the live MOT table
(30d window, screenshots in `screenshots_redesign/`).

## 1. The full diff

Δ = app minus truth in stages; negative = app places EARLIER than reality.

| Technology | n (art.) | App maturity | Truth maturity | Δ | App adoption | Truth adoption | Δ |
|---|---|---|---|---|---|---|---|
| AI data centres | 98 | growth | growth | 0 | early-adopters | early-majority | −1 |
| Grid-scale storage | 69 | growth | dominant-design | −1 | early-majority | early-majority | 0 |
| AI accelerators | 65 | growth | growth | 0 | early-adopters | early-majority | −1 |
| Green hydrogen | 35 | emerging | emerging | **0** | early-adopters | early-adopters | **0** |
| HBM memory | 35 | growth | dominant-design | −1 | early-adopters | late-majority | **−2** |
| Advanced logic ≤3nm | 31 | growth | growth | 0 | early-adopters | early-majority | −1 |
| Quantum computing | 28 | emerging | emerging | **0** | early-adopters | early-adopters | **0** |
| Humanoid robots | 27 | emerging | emerging | **0** | early-adopters | early-adopters | **0** |
| Small modular reactors | 24 | emerging | emerging | **0** | early-adopters | early-adopters | **0** |
| EV charging | 23 | growth | dominant-design | −1 | early-adopters | early-majority | −1 |
| Gene editing / therapy | 23 | research | emerging | −1 | innovators | early-adopters | −1 |
| Generative AI / LLMs | 18 | emerging | dominant-design | **−2** | early-adopters | early-majority | −1 |
| AI drug discovery | 17 | emerging | growth¹ | −1¹ | early-adopters | early-majority¹ | −1¹ |
| Advanced packaging | 15 | growth | growth | 0 | early-adopters | early-majority | −1 |
| Autonomous driving (L4) | 11 | emerging | growth | −1 | early-adopters | early-majority² | −1² |
| Carbon capture | 7 | emerging | emerging | **0** | early-adopters | early-adopters | **0** |
| Solid-state batteries | 6 | research | emerging³ | −1 | innovators | innovators | **0** |
| Critical minerals | 5 | growth | dominant-design⁴ | −1⁴ | — | late-majority⁴ | —⁴ |
| GLP-1 drugs | 5 | research | dominant-design | **−3** | innovators | early-majority | **−2** |
| LFP batteries | 3 | growth | dominant-design | −1 | early-adopters | early-majority→late | −1 |

¹ Scoping caveat: as a *methodology* (top-10 pharma all run multiyear AI-discovery
programs) it's growth/early-majority; scoped to *approved output* (zero AI-designed
approvals yet) it reads emerging. ² Medium confidence — early-majority within
served metros (Waymo 500k paid rides/wk), early-adopters judged globally.
³ Crossed research→emerging within the last ~12 months (first buyable ASSB
product Q1 2026). ⁴ **Category-fit finding:** critical minerals is a supply-chain
capacity story, not a technology — process tech has been dominant-design for
decades; the news is geographic re-diversification (a `strategic_move` story);
the nested new tech (DLE) is emerging. A single lifecycle label is a forced fit.

## 2. The verdict in numbers

Across 39 scoreable stage-axes (20 maturity + 19 adoption):

| | count | share |
|---|---|---|
| Exact match | 16 | 41% |
| One stage EARLY | 19 | 49% |
| Two+ stages EARLY | 4 (GenAI mat, HBM ado, GLP-1 mat −3, GLP-1 ado) | 10% |
| Any stage LATE (over-placed) | **0** | 0% |
| Within-1-stage | 35 | 90% |

**The bias is perfectly unidirectional.** Not one of 23 misses over-places; all
under-place. And the errors are not random: **all six technologies placed exactly
right on both axes are genuinely early** (green H2, quantum, humanoids, SMRs,
carbon capture; + solid-state adoption). The further along the real curve a
technology is, the further behind the app lags — culminating in GLP-1 at
research/innovators when 1 in 8 US adults takes one.

**Adoption is the weaker axis** (7/19 exact vs 9/20 maturity) — 16 of the app's 20
adoption calls are `early-adopters`, because news about mainstream technologies
almost never reads as an "adoption event"; routine pragmatist buying is not news.

## 3. Root-cause classification (each miss, by fix required)

- **Coverage-starved (n<10 articles): GLP-1 (n=5), LFP (n=3), critical minerals
  (n=5).** The worst misses. A 30-day news centroid over 3 articles is noise; these
  should never render as confident dots.
- **News-skew (n≥10 but wrong):** GenAI, HBM, EV charging, grid storage, gene
  editing (n=23 — plenty of coverage, all research-flavored trial news), advanced
  packaging, ≤3nm, AI accelerators, AI data centres, autonomous driving, AI drug
  discovery — all on the adoption axis and/or the growth→dominant-design boundary.
  More articles do NOT fix this: news systematically reports novelty, so the
  centroid of even abundant coverage sits earlier than the world.
- **Taxonomy misfit:** critical minerals — not a technology; the lens can't be
  right because the question is malformed.

## 4. What the page's claims actually are — and the fix path

The placements are a faithful summary of **the last 30 days of news read through
an MOT lens** — and a systematically early-biased estimate of **where technologies
actually are**. News is a good *change detector* (all six correct calls are techs
where news ≈ reality because everything about them is new) and a bad *level
estimator* (established technologies generate novelty-flavored coverage forever).

Recommended, in order:
1. **Coverage floor (S, immediate):** placements with n < 10 stage-classified
   articles render as "insufficient signal" (hollow dot / separate list), not as
   confident placements. Kills the GLP-1/LFP class of embarrassment outright.
2. **Honest captions (XS, immediate):** exhibits say "placed by last-30-days news
   coverage" — and the agent read should stop implying world-state.
3. **Curated anchor stages (M, the real fix):** THIS BENCHMARK IS THE ANCHOR SET.
   Give each tracked technology a curated (stage, as-of, evidence) anchor from §1's
   truth column; news then moves placement *relative to the anchor* (the change
   detector job it's good at). Revisit anchors quarterly — the swing factors are
   documented per technology in the agent outputs.
4. **Fix the tracking taxonomy (S):** split "critical minerals" into the capacity
   story (not lifecycle-tracked) and DLE (tracked, emerging); audit other tracked
   names for the same misfit.
5. **Add this benchmark to `lodestar-eval`** as a recurring tier (re-research
   quarterly, diff vs placements) — placement-vs-world is now a measured metric,
   not a hope. Pairs with the P2 transition-vs-outcome study: anchors fix levels,
   transitions are validated against later outcomes.

## 5. Relation to the rest of the eval

This is a NEW eval layer, not a re-litigation of L3/L5: the gold set grades
*per-article* classification (the lens is decent at that: 69–72% exact vs
provisional gold); L5 verified the placement *math*. Both were necessary, neither
sufficient — a correct centroid over truthfully-classified novelty-skewed articles
still lands early. The failure is in the estimator design (rolling news window
with no memory), which is why the fix is anchors + floors, not another prompt edit.
