# Rubric — Agent Prompt Quality (L1)

Scores each `Agents_prompt/*.md` for how well it steers its Toqan agent. Used by
both an LLM-as-judge and a human reviewer. **The model is chosen on Toqan, not in
the repo — so the prompt is the main quality lever, and the primary thing to
improve before/after a model change (e.g. Fable 5).**

## How to score
Each criterion is scored **0 / 1 / 2** (absent / partial / strong) unless marked
**GATE**. A GATE that fails caps the whole prompt at "needs work" regardless of
other scores — GATE failures are correctness bugs, not style.

Report per prompt: a table of criterion → score → one-line evidence, the total,
and 1–3 concrete rewrite suggestions.

## Universal criteria (all 13 agents)
1. **Role & task clarity** — the agent knows exactly what it is and what one job it does.
2. **Output schema is explicit** — exact keys, types, and **allowed enum values** are
   stated unambiguously (not "return the stage" but the closed vocab).
3. **GATE — Schema/consumer alignment** — the declared output fields + enums match
   what the downstream code actually parses:
   - Extractors → `home_news/parser.py`
   - MOT Lens → `analytics/lens.py` + gold vocab (`maturity_stage`,
     `adoption_stage`, `business_impact`, `scope`)
   Any drift (extra/missing field, renamed key, out-of-vocab value) = **GATE fail**;
   it silently drops or corrupts data.
4. **Grounding / anti-hallucination** — instructed to use only the provided
   source, cite it, and **leave a field null/omit when unsure** rather than guess.
5. **Boundary examples** — worked examples that cover the *hard* cases, not just easy
   ones (for the lens: adjacent-stage boundaries and the chasm).
6. **Edge/failure handling** — empty input, ambiguous item, "nothing qualifies"
   path; explicitly forbids prose/markdown when JSON is expected.
7. **Determinism cues** — debiasing + "one cue → one label" style guidance so the
   same input classifies the same way.
8. **Versioning** — the prompt carries a version marker (ties to
   `lens_prompt_version` attribution).

## Role-specific criteria
**Feed extractors (10):** strict JSON **array**; per-item dedup guidance; ISO date
format; entity-naming normalization; no fabricated fields; graceful non-array
guard (the parser is hardened for this — the prompt should not rely on it).

**MOT Lens:** each MOT dimension defined with its cues; returns a **single modal
stage + a confidence/modal-share signal**; explicit "don't over-stage" / "advance
only when clearly at scale" guidance; distinguishes maturity vs adoption axes.

**Strategist:** every signal must carry **lens + action + impact + horizon +
value-capture + a falsifier + source refs + calibrated confidence**; theory used
correctly (see `mot_scholar.md`); no assertive verbs beyond the evidence; scenarios
grounded; convergence claims cite ≥2 domains.

**Ask:** answers strictly from retrieved context; **valid citations only** (no
phantom document refs); explicit uncertainty/refusal when the corpus can't answer.

## Aggregate
- **Green** ≥ 80% of max and no GATE fail.
- **Amber** 60–80% or a fixable GATE issue.
- **Red** < 60% or an unresolved GATE fail (data-integrity risk).
