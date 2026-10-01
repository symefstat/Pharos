"""
Backtest — would Lodestar's method have called it?

The world-graded forecast record needs time to mature (first resolution
2026-09-10). This module is the credibility bridge: run the SAME method —
headline classification through the MOT lens, quarterly modal-stage rollup,
two-consecutive-readings confirmation — over ARCHIVED news for technologies
whose lifecycle is now settled history, and compare the method's calls against
documented real-world milestones. Misses and false calls are reported with the
same prominence as hits; the point is measurement, not marketing.

Everything here is pure (the runner backtest_run.py does GDELT + agent I/O):
quarterly rollup → stage calls with the production debounce → milestone
comparison → report dict → markdown. Unit-tested with fixtures.
"""

from __future__ import annotations

MATURITY_ORDER = ["research", "emerging", "growth", "dominant-design", "mature", "declining"]

# Production discipline, scaled to quarters: a stage claim needs a minimum of
# classified items in the quarter, and a call only CONFIRMS when the stage
# holds for two consecutive quarters (detect_transitions' run >= 2 debounce).
MIN_ITEMS_PER_QUARTER = 5
CONFIRM_QUARTERS = 2


def quarter_of(date_str: str) -> str:
    """'2021-03-11' → '2021Q1'. Pure."""
    y, m = int(date_str[:4]), int(date_str[5:7])
    return f"{y}Q{(m - 1) // 3 + 1}"


def q_index(q: str) -> int:
    """Comparable integer for a 'YYYYQn' label. Pure."""
    return int(q[:4]) * 4 + int(q[-1]) - 1


def q_span(a: str, b: str) -> int:
    """Signed distance in quarters (b - a). Pure."""
    return q_index(b) - q_index(a)


def quarterly_stages(items: list[dict]) -> list[dict]:
    """Per-quarter modal maturity stage from classified items (pure).

    items: [{date: 'YYYY-MM-DD', maturity_stage: str|None}, …]. 'n/a'/None rows
    count toward nothing. Quarters under MIN_ITEMS_PER_QUARTER get stage=None —
    the same evidence-floor discipline the live product applies."""
    by_q: dict[str, list[str]] = {}
    for it in items:
        stage = (it.get("maturity_stage") or "").strip().lower()
        d = str(it.get("date") or "")
        if len(d) < 7 or stage in ("", "n/a") or stage not in MATURITY_ORDER:
            continue
        by_q.setdefault(quarter_of(d), []).append(stage)
    out = []
    for q in sorted(by_q, key=q_index):
        stages = by_q[q]
        counts: dict[str, int] = {}
        for s in stages:
            counts[s] = counts.get(s, 0) + 1
        modal, n_modal = max(counts.items(), key=lambda kv: (kv[1], MATURITY_ORDER.index(kv[0])))
        n = len(stages)
        out.append({
            "quarter": q,
            "n": n,
            "stage": modal if n >= MIN_ITEMS_PER_QUARTER else None,
            "modal_share": round(n_modal / n, 2) if n else None,
            "counts": counts,
        })
    return out


def stage_calls(quarters: list[dict]) -> list[dict]:
    """The method's dated stage calls (pure): a stage is CALLED in the quarter
    where it has held as the modal stage for CONFIRM_QUARTERS consecutive
    quarters (the production debounce — pending on the first reading, confirmed
    on the second). Only forward moves call; a temporary regression resets
    nothing (the axis is near-monotonic, re-estimation noise is expected)."""
    calls: list[dict] = []
    called_upto = -1                      # highest MATURITY_ORDER index already called
    streak_stage: str | None = None
    streak = 0
    for row in quarters:
        s = row["stage"]
        if s is None:
            streak_stage, streak = None, 0    # an evidence gap breaks the streak
            continue
        if s == streak_stage:
            streak += 1
        else:
            streak_stage, streak = s, 1
        idx = MATURITY_ORDER.index(s)
        if idx > called_upto and streak >= CONFIRM_QUARTERS:
            calls.append({"stage": s, "quarter": row["quarter"],
                          "evidence_n": row["n"], "modal_share": row["modal_share"]})
            called_upto = idx
    return calls


def compare(calls: list[dict], milestones: list[dict]) -> list[dict]:
    """Milestone-by-milestone verdict (pure). Each milestone is a documented
    real-world event mapped to the stage it marks: {stage, quarter, event,
    source}. lag_quarters = call − milestone (negative = the method called it
    BEFORE the event; positive = after; None = never called → MISS)."""
    by_stage = {c["stage"]: c for c in calls}
    out = []
    for m in milestones:
        c = by_stage.get(m["stage"])
        out.append({
            **m,
            "called_quarter": c["quarter"] if c else None,
            "lag_quarters": q_span(m["quarter"], c["quarter"]) if c else None,
            "hit": c is not None,
        })
    return out


def false_calls(calls: list[dict], milestones: list[dict]) -> list[dict]:
    """Calls for stages that have NO milestone — candidate false signals (pure).
    Reported with the misses: an over-eager method is as broken as a deaf one."""
    marked = {m["stage"] for m in milestones}
    return [c for c in calls if c["stage"] not in marked]


def build_report(case: dict, items: list[dict]) -> dict:
    """One technology's full backtest result (pure). `case` carries key/label/
    query/window/milestones/notes; `items` are the dated, lens-classified
    headlines."""
    quarters = quarterly_stages(items)
    calls = stage_calls(quarters)
    comparison = compare(calls, case["milestones"])
    return {
        "key": case["key"],
        "label": case["label"],
        "window": case["window"],
        "query": case["query"],
        "n_items": len(items),
        "n_classified": sum(1 for it in items
                            if (it.get("maturity_stage") or "").strip().lower()
                            in MATURITY_ORDER),
        "quarters": quarters,
        "calls": calls,
        "comparison": comparison,
        "false_calls": false_calls(calls, case["milestones"]),
        "notes": case.get("notes"),
    }


def _lag_word(lag: int | None) -> str:
    if lag is None:
        return "**MISS — never called**"
    if lag == 0:
        return "same quarter"
    if lag < 0:
        return f"**{-lag} quarter{'s' if lag != -1 else ''} early**"
    return f"{lag} quarter{'s' if lag != 1 else ''} late"


def report_to_markdown(reports: list[dict], generated: str) -> str:
    """The study document (pure) — same honesty standard as the Methodology
    page: method stated up front, misses and false calls in the same table as
    the hits, every milestone carrying its public source."""
    hits = sum(1 for r in reports for c in r["comparison"] if c["hit"])
    total = sum(len(r["comparison"]) for r in reports)
    n_false = sum(len(r["false_calls"]) for r in reports)
    lines = [
        "# Lodestar backtest — would the method have called it?",
        "",
        f"_Generated {generated} · reproducible via `python backend/backtest_run.py`_",
        "",
        "**Method.** For each settled technology, historical headlines are pulled "
        "from the GDELT news archive per quarter, classified through the SAME MOT "
        f"lens agent the live product uses (headline + summary only), rolled up to "
        f"a quarterly modal maturity stage (evidence floor ≥{MIN_ITEMS_PER_QUARTER} "
        f"classified items/quarter), and a stage is *called* only after holding for "
        f"{CONFIRM_QUARTERS} consecutive quarters — the production debounce. Calls "
        "are then compared with documented real-world milestones. Misses and "
        "uncorroborated calls are reported alongside the hits.",
        "",
        f"**Headline result: {hits}/{total} milestones called · "
        f"{n_false} uncorroborated call{'s' if n_false != 1 else ''}.**",
        "",
        "**Limitations.** GDELT sampling is coarse (a slice of each quarter's "
        "coverage, English only); milestone dates are curated judgments (each "
        "carries its public source); and the lens prompt is today's — this "
        "measures the current method on old news, not what Lodestar would have "
        "shipped at the time.",
        "",
        "**What this actually validates.** The backtest grades the RAW, "
        "unanchored news signal — and it confirms, on settled history, exactly "
        "the bias the gold-set evaluation measured on the present: headline "
        "classification is a systematically *early/conservative* level "
        "estimator (mRNA read 'research' through the EUA quarter; NFTs never "
        "left 'emerging' through boom or bust). News is a change detector, not "
        "a level detector. This is precisely why the live product floors every "
        "placement with a dated, curated anchor and why transitions require a "
        "confirming snapshot: the anchors supply the level, the news supplies "
        "the change. The honest conclusion is not 'the method works unaided' — "
        "it is that the anchor architecture is load-bearing, and this study is "
        "the measurement that proves it.",
        "",
    ]
    for r in reports:
        lines += [f"## {r['label']}",
                  "",
                  f"_Window {r['window'][0]} → {r['window'][1]} · query `{r['query']}` · "
                  f"{r['n_classified']}/{r['n_items']} headlines stage-classified_",
                  ""]
        if r.get("notes"):
            lines += [f"_{r['notes']}_", ""]
        lines += ["| Milestone (documented) | Quarter | Method called | Verdict |",
                  "| --- | --- | --- | --- |"]
        for c in r["comparison"]:
            called = c["called_quarter"] or "—"
            lines.append(f"| {c['event']} ([source]({c['source']})) | {c['quarter']} "
                         f"| {called} | {_lag_word(c['lag_quarters'])} |")
        if r["false_calls"]:
            lines += ["",
                      "Uncorroborated calls (no matching milestone — candidate false signals):"]
            for c in r["false_calls"]:
                lines.append(f"- `{c['stage']}` called {c['quarter']} "
                             f"(n={c['evidence_n']}, {int((c['modal_share'] or 0) * 100)}% modal)")
        lines += ["", "Quarterly read (modal stage · n items):", ""]
        lines.append("| " + " | ".join(q["quarter"] for q in r["quarters"]) + " |")
        lines.append("|" + "---|" * len(r["quarters"]))
        lines.append("| " + " | ".join(
            f"{q['stage'] or '(<floor)'} · {q['n']}" for q in r["quarters"]) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
