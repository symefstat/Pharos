---
name: lodestar-eval
description: Run the Lodestar end-to-end evaluation — unit suite, gold-set validation, prompt schema-drift audit, judge self-tests, API↔UI parity, and (user-gated) live Supabase/Toqan scoring, lens A/B, strategist and Ask judging — then render the scorecard. Use this skill whenever the user wants to evaluate, score, audit, regression-check, or benchmark Lodestar or its pipeline; before/after ANY prompt edit in backend/Agents_prompt/ or any Toqan model change (e.g. a Fable 5 upgrade — run it before and after and diff); before a demo or release; or when they ask "did the model/prompt change help?", "is the eval green?", "re-run the eval", or mention the gold set, lens accuracy, the A/B, or the scorecard. Also use it to check a single layer (L1–L10) — the runner and per-layer tools are all wrapped here.
---

# lodestar-eval

One command re-runs the eval built on 2026-07-02 (reports: `backend/eval/reports/00–30`).
Three tiers; only tier 0 is free of production access.

## Quick start

```bash
# Tier 0 — offline, $0, no creds (default; run this before every commit/prompt edit)
./venv/bin/python Skills/lodestar-backend/eval/scripts/run_eval.py

# Tier 1 — + Supabase reads ($0 LLM): freshness, rollup integrity, lens scoring
./venv/bin/python Skills/lodestar-backend/eval/scripts/run_eval.py --live-db --i-approve-live

# Tier 2 — + Toqan spend: lens A/B, strategist judging, Ask retrieval
./venv/bin/python Skills/lodestar-backend/eval/scripts/run_eval.py --live-db --live-llm --i-approve-live
```

Exit 0 = green. `--json` for machine-readable, `--skip-tests` for a fast re-check.

**GATE: never pass `--i-approve-live` without the user's explicit go in this
conversation.** Tier 1 reads production; tier 2 costs real money. Before asking,
read `references/live_playbook.md` and quote the cost table to the user. The
playbook also holds the **model-change protocol** (the before/after A/B procedure
and the recorded baselines a Fable 5 upgrade must beat).

## What tier 0 checks (and what "green" means)

| Check | Tool | Green means |
|---|---|---|
| Unit suite | `pytest -q` | regression floor intact (~379 tests) |
| Gold validation | `backend/eval_run.py --validate-gold` | gold parses, in-vocab, deduped |
| Harness smoke | `backend/eval_run.py --from-fixture` | scorecard renders end-to-end |
| L1 schema drift (GATE) | `backend/eval/judges/prompt_audit.py` | 0 prompt↔consumer mismatches |
| L8 judge self-test | `strategist_eval.py --from-fixture` ×2 | clean brief passes AND seeded defects are caught (defective fixture MUST exit 1) |
| L9 judge self-test | `ask_eval.py --demo` | seeded phantom/ungrounded rows caught (MUST exit 1) |
| L10 parity | `backend/eval/app_parity_check.py` | static API↔UI diff prints (informational) |

The runner auto-selects the gold file (human-verified > provisional > seed) and
warns when scores are provisional/circular.

## Interpreting results

- Acceptance targets are **pre-committed** in `backend/eval/reports/00_baseline.md` §5 —
  compare actuals against those, never against vibes. Add Wilson CIs for any
  accuracy on n≲300 (the 03 report shows the format).
- A schema-drift finding is a **bug, not a style issue** — it silently drops data.
- Known-open issues you should not re-report as new: `backend/eval/reports/30_scorecard.md`
  §2 is the fix backlog (P0 items 1–8 are the trust blockers).
- After a lens prompt/model change, the number to beat is in
  `references/live_playbook.md` §model-change protocol.

## Layer map (for single-layer asks)

L1 prompts → `prompt_audit.py` + rubric `backend/eval/rubrics/prompt_quality.md` ·
L2 extraction → parser tests + live faithfulness (playbook) ·
L3 lens ⭐ → gold set + `backend/eval_run.py` + `backend/lens_ab.py` ·
L4 rollup → `backend/eval_run.py --from-supabase` ·
L5 tech layer → `tests/test_tech_layer_golden.py` ·
L6 financials → `backend/eval/judges/finance_spotcheck.py` (live) ·
L7 forecasts → tests + backtest (playbook) ·
L8 strategist → `strategist_eval.py` + rubrics `mot_scholar.md`, `falsifier.md` ·
L9 ask → `ask_eval.py` + `ask_questions.jsonl` ·
L10 app → `app_parity_check.py` + headless drive (playbook).

## Reporting

Write run results into `backend/eval/reports/` (dated), update the scorecard workbook
(`lodestar_eval_scorecard.xlsx`) if verdicts changed, and summarize
actual-vs-target with the same PASS/FAIL framing as `30_scorecard.md`. If the
gold set is provisional, say so in the first line of any accuracy claim.
