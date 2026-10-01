# Pharos gold set + eval harness

The gold set is the **one irreplaceable input** to the measurement foundation: a
hand-labelled set of articles with their *true* MOT classification. Every
"did the lens get better?" / "is the data clean?" question is answered by scoring
the pipeline's output against it. Without it, nothing downstream is provable.

> The harness scaffolding (this folder + `backend/eval_run.py`) is built and tested.
> **Labelling `gold_labels.jsonl` is the human step — that's you.**

## 1. The file: `backend/eval/gold_labels.jsonl`

One JSON object per line (JSONL). `gold_labels.example.jsonl` shows the shape.
`url` is required (it's the join key against the feed tables); every label field
is **optional** — leave a field out (or null) when the article doesn't cleanly
carry that signal, and it simply won't be scored.

| field             | required | allowed values |
|-------------------|----------|----------------|
| `url`             | yes      | the article URL, exactly as stored in its feed table |
| `maturity_stage`  | no       | `research`, `emerging`, `growth`, `dominant-design`, `mature`, `declining`, `n/a` |
| `adoption_stage`  | no       | `innovators`, `early-adopters`, `early-majority`, `late-majority`, `laggards`, `n/a` |
| `business_impact` | no       | `material`, `contextual`, `none` |
| `scope`           | no       | `single-company`, `sector`, `regulatory`, `comparison`, `deal` |
| `feed`            | no       | feed key (`ev`, `biotech`, …) — context only, not scored |
| `notes`           | no       | your rationale — not scored, but invaluable when re-reading a disagreement |

Values are normalised on load (lowercased, `_`→`-`), so `Early_Majority` ==
`early-majority`. The allowed lists are imported straight from the pipeline
(`analytics/lens.py`, `home_news/parser.py`) — they can't drift from it.

## 2. How to label

- **Aim for ~150–300 articles**, spread across feeds and across stages (don't let
  it skew to one domain or one easy stage — the confusion matrix needs coverage
  of the adjacent-stage boundaries the lens struggles with).
- **Label only what you're sure of.** A regulatory action may have a clear `scope`
  and `business_impact` but no meaningful `maturity_stage` — leave the latter out.
- **Capture the boundary calls.** The articles worth labelling are the ones near a
  stage boundary (emerging↔growth, growth↔dominant-design, the chasm at
  early-adopters↔early-majority) — those are what the lens gets wrong. Use `notes`
  to record the discriminator you used.
- Pull `url`s straight from the feed tables (or the Explore tab) so the join hits.

## 3. Validate before you trust it

```bash
./venv/bin/python backend/eval_run.py --validate-gold
```

Reports duplicate URLs, values outside the allowed vocab, and rows that label
nothing. Fix until it's clean.

## 4. Run the eval

Offline self-test (scores a fixture of predictions against the example gold —
this is the exact smoke CI runs; no DB, no agent calls):

```bash
./venv/bin/python backend/eval_run.py --gold backend/eval/gold_labels.example.jsonl \
    --from-fixture backend/eval/predictions.fixture.jsonl
```

Live (fetches predictions from Supabase by joining on `url` — **needs DB creds**,
so confirm before running):

```bash
./venv/bin/python backend/eval_run.py --from-supabase
```

Both print a scorecard: extraction completeness, per-field accuracy + a confusion
matrix per field, and (live) a rollup-integrity recompute-and-diff. Use it to A/B
the old vs tightened lens prompt (Phase 1.1) and keep the winner.
