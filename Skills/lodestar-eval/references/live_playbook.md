# lodestar-eval — live-run playbook (tiers 1–2) and model-change protocol

Read this before any `--live-db` / `--live-llm` run, and before/after any Toqan
model or prompt change (e.g. a Fable 5 upgrade).

## Ground rules (non-negotiable)

1. **Ask the user before anything live.** Tier 1 reads production; tier 2 spends
   money. State what will run and the cost estimate; wait for an explicit go;
   then pass `--i-approve-live`.
2. **Never write to production tables.** Every live eval path classifies/scores
   in memory (the `lens_ab.py` pattern). If you add a new live check, it must
   follow the same pattern.
3. **Never echo `.env` contents.** Report *which key* is missing by name only
   (e.g. "`TOQAN_ASK` is empty"), never values.

## Cost table (measured 2026-07-02)

| Check | Calls | Cost class |
|---|---|---|
| freshness + rollup integrity + scoring | ~30 Supabase SELECTs | $0 LLM |
| lens A/B (199-row gold) | 19 batched Toqan calls, ~30–60 min | the big one |
| strategist deterministic (live brief) | 1 Supabase SELECT | $0 LLM |
| strategist 3-judge panel | signals × 3 Toqan calls (~15) | needs `TOQAN_JUDGE` |
| ask live (29 questions) | 29 embeddings + 29 pgvector + 29 Toqan | needs `TOQAN_ASK` |
| L2 faithfulness (agent-judged) | ~15 SELECTs + ~100 page fetches | judged in-session |
| L6 finance spot-check | ~30 yfinance calls | $0 LLM |
| L7 forecast backtest | SELECT-only | $0 LLM |

## Known gate states (update when they change)

- `TOQAN_ASK` was **empty** in `.env` as of 2026-07-02 → ask answer-leg skips
  (retrieval-only). Saved retrieval captures: `eval/reports/ask_live_capture_20260702.jsonl`.
- `TOQAN_JUDGE` not provisioned → strategist panel falls back to deterministic-only;
  the 2026-07-02 panel scores were produced by in-session judging (correlated-judge
  bias flagged) — re-run with real independent judges when the key exists.

## Gold-set discipline

- The runner auto-picks the best gold file: `gold_labels.jsonl` (human-verified) >
  `.provisional.jsonl` (triage-corrected) > `.seed.jsonl` (circular — warns).
- **Rolling refresh:** add ~25 fresh hand-checked labels/month (`gold_seed.py`
  drafts them; a human corrects; append). Old URLs age out of the 1000-row read
  window (54/200 had aged out within weeks) and stale gold invites contamination.
- After any human review: `eval_run.py --validate-gold` must be clean before scoring.

## Model/prompt-change protocol (the Fable 5 procedure)

Run **before** the change, then **after**, and diff:

1. Tier 0 must be green both times (schema drift after a prompt edit = stop).
2. `lens_ab.py --gold <gold>` — the recorded pre-change baseline (2026-07-02,
   provisional gold, n=146): **v2 single-shot maturity 63.0% / adoption 63.7%;
   stored-reconciled 68.5% / 70.5%.** A new model/prompt must beat single-shot
   and should close on reconciled.
3. `strategist_eval.py --from-supabase` on a fresh brief — baseline: grounding
   100% (after unit-normalization adjudication), theory fidelity **1.6/3**,
   falsifier **10.8/12**, overclaim **20%** deterministic.
4. `ask_eval.py --live` — baseline: precision@5 **0.94**; answer-leg unmeasured.
5. Write the delta into `eval/reports/` as `ab_<change>_<date>.md`. Newer ≠
   better until this file says so.

## Acceptance targets

Pre-committed in `eval/reports/00_baseline.md` §5 — do not renegotiate them after
seeing results; if a target changes, change it *before* the run and note why.

## Standing findings a live run should re-check

The September 2026 headline cliff (L7 quarantine leak), the stale-FX class of
error (L6), extraction fabrications (L2: 3/94 sampled), the n/a-boundary lens
errors (L3: 44% of maturity misses), dead payload fields (L10). Fix list:
`eval/reports/30_scorecard.md` §2.
