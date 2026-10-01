# Rubric — Falsifier Quality (L8)

Every Strategist signal must carry a **falsifier** — a concrete, dated condition
that, if it occurred, would prove the call wrong. This is the app's core honesty
feature; a vague falsifier is worse than none because it *looks* rigorous. Judge
each signal's falsifier here.

## Criteria — score each 0 / 1 / 2
1. **Specific** — names a concrete, observable event or metric (not "adoption may
   slow"). *0* vague · *2* names the exact thing to watch.
2. **Time-bound** — carries a deadline / window (e.g. "by Q4 2026"). *0* no date ·
   *2* clear date.
3. **Refuting (directionally correct)** — if it happened, it would genuinely
   **contradict** the signal — not be orthogonal, and not something already implied
   by the signal being true. *0* doesn't actually refute · *2* cleanly refutes.
4. **Measurable threshold** — a checkable number/observable ("GMV declines >20%",
   ">50% 2nm capacity increase"), not a mood. *0* no threshold · *2* crisp threshold.
5. **Checkable** — resolvable against the system's own data (stage history, deal
   flow, prices, forecast ledger) or public record. *0* unresolvable · *2* clearly
   resolvable, ideally auto-resolvable.
6. **Non-trivial** — not near-certain either way; a real test, not a formality.
   *0* trivially true/false · *2* genuinely uncertain.

## Reference calls (from a real briefing)
- **Strong** — *"Tether gains MiCA authorization or launches a compliant stablecoin
  by Q4 2026"* → specific, dated, refuting, checkable. Score ~11–12/12.
- **Strong** — *"UK BNPL GMV declines >20% by Q4 2026 post-regulation"* → measurable
  threshold, dated, auto-resolvable.
- **Weak** — *"AI infrastructure demand may not scale as expected"* → no date, no
  threshold, not clearly refuting. Score ≤ 4/12.

## Aggregate
Per-signal total /12. **Green ≥ 9 · Amber 6–8 · Red < 6.** Any signal with **no
falsifier**, or one scoring 0 on criterion 3 (doesn't actually refute), is an
automatic fix item — flag it separately from the mean.
