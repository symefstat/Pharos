#!/usr/bin/env python3
"""
lodestar-eval runner — tiered, gate-respecting orchestrator for the full eval.

  TIER 0 (default, offline, $0, no creds):
    unit suite → gold validation → harness smoke → prompt schema-drift audit →
    strategist judge self-test (clean must pass, seeded-defect must fail) →
    ask judge self-test → API↔UI parity check.

  TIER 1 (--live-db, Supabase READS only, $0 LLM):
    freshness check → rollup integrity + lens scoring vs the gold set.

  TIER 2 (--live-llm, real Toqan cost):
    lens A/B (~1 batched call per ~8 gold articles) →
    strategist deterministic checks on the live brief
    (+ 3-judge panel if TOQAN_JUDGE is set) →
    ask live retrieval (+ answers if TOQAN_ASK is set).

Tiers 1–2 refuse to run without --i-approve-live: live runs read production
and (tier 2) spend money. Nothing here ever writes to production tables —
every live path follows lens_ab.py's classify-in-memory pattern.

Exit code: 0 = all selected checks green · 1 = at least one failure.
Usage:
  ./venv/bin/python Skills/lodestar-eval/scripts/run_eval.py            # tier 0
  ./venv/bin/python ... --live-db --i-approve-live                     # + tier 1
  ./venv/bin/python ... --live-db --live-llm --i-approve-live          # everything
  ./venv/bin/python ... --json                                        # machine-readable
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root (Skills/lodestar-eval/scripts/..)
PY = str(ROOT / "venv" / "bin" / "python")

GOLD_CANDIDATES = [
    "eval/gold_labels.jsonl",             # human-verified (the real one)
    "eval/gold_labels.provisional.jsonl", # triage-corrected, human sign-off pending
    "eval/gold_labels.seed.jsonl",        # raw lens guesses — circular, last resort
]


def pick_gold() -> tuple[str, str]:
    for i, rel in enumerate(GOLD_CANDIDATES):
        if (ROOT / rel).exists():
            tier = ["human-verified", "PROVISIONAL (human sign-off pending)",
                    "SEED — circular, scores are not accuracy"][i]
            return rel, tier
    sys.exit("no gold file found under eval/ — run gold_seed.py first")


def run(name: str, cmd: list[str], expect: int = 0, timeout: int = 3600) -> dict:
    print(f"\n───── {name}\n$ {' '.join(cmd)}")
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print("  TIMEOUT")
        return {"name": name, "ok": False, "detail": f"timeout after {timeout}s"}
    tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-8:])
    print(tail)
    ok = p.returncode == expect
    verdict = "OK" if ok else f"FAIL (exit {p.returncode}, expected {expect})"
    print(f"  → {verdict}")
    return {"name": name, "ok": ok, "exit": p.returncode, "expected": expect}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    ap.add_argument("--live-db", action="store_true", help="tier 1: Supabase reads ($0 LLM)")
    ap.add_argument("--live-llm", action="store_true", help="tier 2: Toqan calls (real cost)")
    ap.add_argument("--i-approve-live", action="store_true",
                    help="required with --live-db/--live-llm: confirms the human approved production reads / LLM spend")
    ap.add_argument("--skip-tests", action="store_true", help="skip the pytest suite (fast re-check)")
    ap.add_argument("--json", action="store_true", help="emit a JSON summary line at the end")
    args = ap.parse_args()

    if (args.live_db or args.live_llm) and not args.i_approve_live:
        sys.exit("REFUSING: --live-db/--live-llm hit production (and tier 2 costs money). "
                 "Get explicit user approval, then re-run with --i-approve-live.")

    gold, gold_tier = pick_gold()
    print(f"gold set: {gold}  [{gold_tier}]")
    results: list[dict] = []

    # ── Tier 0 — offline ────────────────────────────────────────────────
    if not args.skip_tests:
        results.append(run("unit suite", [PY, "-m", "pytest", "-q"]))
    results.append(run("gold validation", [PY, "eval_run.py", "--validate-gold", "--gold", gold]))
    results.append(run("harness smoke (fixture)",
                       [PY, "eval_run.py", "--gold", "eval/gold_labels.example.jsonl",
                        "--from-fixture", "eval/predictions.fixture.jsonl"]))
    results.append(run("prompt schema-drift audit (L1 GATE)", [PY, "eval/judges/prompt_audit.py"]))
    results.append(run("strategist judge self-test: clean brief passes",
                       [PY, "eval/judges/strategist_eval.py", "--from-fixture",
                        "eval/judges/fixtures/brief_clean.json"]))
    results.append(run("strategist judge self-test: seeded defects caught",
                       [PY, "eval/judges/strategist_eval.py", "--from-fixture",
                        "eval/judges/fixtures/brief_defective.json"], expect=1))
    results.append(run("ask judge self-test: seeded defects caught",
                       [PY, "eval/judges/ask_eval.py", "--demo"], expect=1))
    results.append(run("API↔UI parity check (L10)", [PY, "eval/app_parity_check.py"]))

    # ── Tier 1 — live DB reads ($0 LLM) ─────────────────────────────────
    if args.live_db:
        results.append(run("freshness check", [PY, "freshness_check.py"]))
        results.append(run(f"rollup integrity + lens scoring vs {gold}",
                           [PY, "eval_run.py", "--from-supabase", "--gold", gold]))

    # ── Tier 2 — live LLM (Toqan cost) ──────────────────────────────────
    if args.live_llm:
        results.append(run(f"lens A/B vs {gold} (Toqan, non-destructive)",
                           [PY, "lens_ab.py", "--gold", gold], timeout=5400))
        results.append(run("strategist deterministic checks on live brief",
                           [PY, "eval/judges/strategist_eval.py", "--from-supabase"]))
        results.append(run("ask live retrieval eval",
                           [PY, "eval/judges/ask_eval.py", "--live"], timeout=5400))

    # ── Summary ─────────────────────────────────────────────────────────
    fails = [r for r in results if not r["ok"]]
    print("\n" + "=" * 64)
    print(f"lodestar-eval: {len(results) - len(fails)}/{len(results)} checks green"
          f"  (gold: {gold_tier})")
    for r in fails:
        print(f"  FAIL: {r['name']}")
    if gold_tier.startswith("PROVISIONAL") or gold_tier.startswith("SEED"):
        print(f"  NOTE: gold set is {gold_tier} — treat accuracy numbers accordingly.")
    print("=" * 64)
    if args.json:
        print(json.dumps({"green": len(results) - len(fails), "total": len(results),
                          "gold": gold, "gold_tier": gold_tier, "checks": results}))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
