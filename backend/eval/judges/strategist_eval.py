#!/usr/bin/env python3
"""
L8 Strategist judge harness — deterministic checks (offline) + gated LLM panel.

Evaluates a stored Strategist brief (the `strategist_briefs` row shape:
`strategic_read` + its `stories`/`theory` source sets) against the L8 acceptance
targets in EVAL_PLAN.md:

  DETERMINISTIC (no LLM, no network — always safe to run):
    1. Grounding    — every numeric claim in a signal's text must appear in the
                      signal's cited [S#] items (normalized: "€3.2 billion" ==
                      "3.2bn"; "90%" == "90 percent"). Hallucinated = in no
                      source at all; misattributed = in a source the signal
                      didn't cite (warn, not a hallucination).
    2. S#/T# refs   — every id in `sources` and every inline [S#]/[T#] must
                      resolve to a real item in the brief's source/theory set.
    3. Falsifier    — presence + the *mechanical* half of backend/eval/rubrics/falsifier.md:
                      criterion 2 (time-bound: has a date/window) and criterion 4
                      (measurable threshold: comparator/number). /4 per signal.
    4. Overclaim    — assertive-verb lexicon scan ("wins", "confirms", "proves",
                      "guarantees", ...) with an evidence-strength heuristic: a
                      hit is a violation unless confidence=high AND >=2 valid
                      cited sources. Falsifiers are exempt (hypotheticals).

  LLM-JUDGE PANEL (gated behind --live-judge; NEVER runs without explicit creds):
    3 independent judges per signal score backend/eval/rubrics/mot_scholar.md (theory
    fidelity 0-3 + misapplication flag) and backend/eval/rubrics/falsifier.md (/12);
    judge #3 is explicitly prompted to REFUTE the signal. Majority rules
    (median score; misapplication only if >=2 judges flag it). Wiring mirrors
    lens_ab.py / analytics.strategist: toqan.client.ToqanAgent with a
    dedicated key (TOQAN_JUDGE), imported lazily so the offline path never
    touches network code.

Usage (offline, safe):
    ./venv/bin/python -m eval.judges.strategist_eval --from-fixture backend/eval/judges/fixtures/brief_clean.json
    ./venv/bin/python -m eval.judges.strategist_eval --from-fixture backend/eval/judges/fixtures/brief_defective.json --json

Live paths:
    --from-supabase            # read latest brief from strategist_briefs (SELECT-only)
    --live-judge               # GATED: raises NEEDS APPROVAL without TOQAN_JUDGE

Exit code: 0 if all deterministic acceptance targets pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parents[2]
RUBRIC_DIR = REPO_ROOT / "eval" / "rubrics"
ENV_KEY_JUDGE = "TOQAN_JUDGE"  # dedicated judge key; NOT the Strategist's key
PANEL_SIZE = 3

# Signal fields whose numeric claims must be grounded in cited sources. The
# falsifier is deliberately EXCLUDED: its numbers are forward-looking thresholds
# ("declines >20% by Q4 2026"), not claims about the sources.
GROUNDING_FIELDS = ("title", "implication", "action_rationale", "value_capture")

# ── acceptance targets (EVAL_PLAN.md §L8) ───────────────────────────────────
TARGET_GROUNDING_PCT = 95.0     # and 0 hallucinated numbers
TARGET_SREF_PCT = 100.0         # every S#/T# resolves
TARGET_OVERCLAIM_PCT = 10.0     # <=10% of signals
TARGET_FALSIFIER_MECH = 3.0     # /4 mean (dated + threshold), none missing
# Live-panel targets (LLM judges): theory fidelity mean >=2.0 with 0
# misapplications; falsifier mean >=9/12 with none missing/non-refuting.


# ═════════════════════════════════════════════════════════════════════════════
# 1. Numeric-claim extraction + normalized matching (grounding)
# ═════════════════════════════════════════════════════════════════════════════

_SCALE = {
    "trillion": 1e12, "tn": 1e12,
    "billion": 1e9, "bn": 1e9,
    "million": 1e6, "mn": 1e6,
    "thousand": 1e3, "k": 1e3,
}

# A number token: optional currency, digits (with commas/decimals), optionally an
# attached alpha unit ("2nm", "3.2bn", "5G") and/or a separated %/scale word.
# Leading (?<![\w.]) rejects "Q4"->4, "S1"->1, "v2.0"->0.
_NUM_RE = re.compile(
    r"(?<![\w.])(?P<cur>[$€£¥])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<attached>[a-zA-Z]{1,4})?"
    r"(?:\s?(?P<pct>%)|\s(?P<word>percent(?:age\s+points)?|trillion|billion|million|thousand|bn|mn|tn|bps)\b)?"
)


def _canonical(num: float, cur: str | None, pct: bool, scale_word: str | None) -> tuple[str, float]:
    """(claim class, canonical value). Scale words multiply; % / currency are classes."""
    mult = _SCALE.get((scale_word or "").lower(), 1.0)
    value = num * mult
    if pct:
        return "pct", num
    if cur:
        return "currency", value
    if mult != 1.0:
        return "scaled", value
    return "bare", value


def extract_numeric_claims(text: str) -> list[dict]:
    """Extract numeric claims from `text`.

    Each claim: {raw, mantissa, value, cls, advisory}. `advisory` claims (bare
    4-digit years 1900-2099, bare single digits like "3 players") are reported
    but excluded from the grounding % — they are usually dates/counts, not
    figures lifted from a source.
    """
    claims = []
    for m in _NUM_RE.finditer(text or ""):
        mantissa = m.group("num").replace(",", "")
        num = float(mantissa)
        attached = (m.group("attached") or "")
        pct = bool(m.group("pct")) or (m.group("word") or "").startswith("percent")
        scale_word = m.group("word") if (m.group("word") or "").lower() in _SCALE else None
        if attached.lower() in _SCALE:            # "3.2bn"
            scale_word, attached = attached, ""
        cls, value = _canonical(num, m.group("cur"), pct, scale_word)

        unit_token = None
        if attached:                              # "2nm", "5G" — match the whole token
            cls = "unit"
            unit_token = (m.group("num") + attached).lower()

        advisory = False
        if cls == "bare":
            if 1900 <= num <= 2099 and num == int(num) and "." not in mantissa:
                cls, advisory = "year", True
            elif num < 10 and "." not in mantissa:
                advisory = True

        claims.append({
            "raw": m.group(0).strip(), "mantissa": mantissa, "value": value,
            "cls": cls, "unit_token": unit_token, "advisory": advisory,
        })
    return claims


def _norm_text(text: str) -> str:
    return (text or "").lower().replace(",", "")


def _source_text(item: dict) -> str:
    return " ".join(str(item.get(k) or "") for k in ("title", "summary"))


def _claim_in_text(claim: dict, norm_text: str, source_values: set[float]) -> bool:
    """Normalized match: mantissa with digit boundaries, unit token, or
    scale-equivalent canonical value ("€3.2 billion" vs "3.2bn")."""
    if claim["unit_token"] and claim["unit_token"] in norm_text:
        return True
    pat = r"(?<![\d.])" + re.escape(claim["mantissa"]) + r"(?![\d.])"
    if re.search(pat, norm_text):
        return True
    return any(math.isclose(claim["value"], v, rel_tol=1e-6) for v in source_values)


def check_grounding(read: dict, stories: list[dict]) -> dict:
    """Match every numeric claim in every signal against its cited sources."""
    by_label = {s.get("label"): s for s in stories if s.get("label")}
    src_norm = {lb: _norm_text(_source_text(s)) for lb, s in by_label.items()}
    src_vals = {
        lb: {c["value"] for c in extract_numeric_claims(_source_text(s))}
        for lb, s in by_label.items()
    }

    hard = grounded = 0
    hallucinated, misattributed, advisory_unmatched = [], [], []
    for i, sig in enumerate(read.get("signals") or [], 1):
        cited = [r for r in (sig.get("sources") or []) if r in by_label]
        scan = cited or list(by_label)  # no valid sources -> scan all, S#-check flags it
        text = " ".join(str(sig.get(f) or "") for f in GROUNDING_FIELDS)
        std = sig.get("standards") or {}
        if isinstance(std, dict):
            text += " " + str(std.get("read") or "")
        for claim in extract_numeric_claims(text):
            in_cited = any(_claim_in_text(claim, src_norm[lb], src_vals[lb]) for lb in scan)
            in_any = in_cited or any(
                _claim_in_text(claim, src_norm[lb], src_vals[lb]) for lb in by_label
            )
            where = {"signal": i, "title": sig.get("title"), "claim": claim["raw"]}
            if claim["advisory"]:
                if not in_any:
                    advisory_unmatched.append(where)
                continue
            hard += 1
            if in_cited:
                grounded += 1
            elif in_any:
                misattributed.append(where)
            else:
                hallucinated.append(where)

    pct = 100.0 * grounded / hard if hard else 100.0
    return {
        "hard_claims": hard, "grounded": grounded, "pct": round(pct, 1),
        "hallucinated": hallucinated, "misattributed": misattributed,
        "advisory_unmatched": advisory_unmatched,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 2. S# / T# reference validity
# ═════════════════════════════════════════════════════════════════════════════

_INLINE_REF_RE = re.compile(r"\[([ST]\d+)\]")


def check_references(read: dict, stories: list[dict], theory: list[dict]) -> dict:
    s_labels = {s.get("label") for s in stories}
    t_labels = {t.get("label") for t in theory}
    total = valid = 0
    phantom, no_sources = [], []
    for i, sig in enumerate(read.get("signals") or [], 1):
        refs = list(sig.get("sources") or [])
        if not refs:
            no_sources.append({"signal": i, "title": sig.get("title")})
        text = " ".join(str(sig.get(f) or "") for f in
                        ("title", "implication", "action_rationale", "value_capture", "falsifier"))
        refs += _INLINE_REF_RE.findall(text)
        for r in refs:
            total += 1
            ok = (r in s_labels) if r.startswith("S") else (r in t_labels)
            if ok:
                valid += 1
            else:
                phantom.append({"signal": i, "title": sig.get("title"), "ref": r})
    # bottom-line inline refs too
    for r in _INLINE_REF_RE.findall(str(read.get("bottom_line") or "")):
        total += 1
        ok = (r in s_labels) if r.startswith("S") else (r in t_labels)
        valid += 1 if ok else 0
        if not ok:
            phantom.append({"signal": 0, "title": "(bottom_line)", "ref": r})
    pct = 100.0 * valid / total if total else 100.0
    return {"refs": total, "valid": valid, "pct": round(pct, 1),
            "phantom": phantom, "signals_without_sources": no_sources}


# ═════════════════════════════════════════════════════════════════════════════
# 3. Falsifier — mechanical half of backend/eval/rubrics/falsifier.md
# ═════════════════════════════════════════════════════════════════════════════

_DATE_RE = re.compile(
    r"\b(20\d{2}|[qh][1-4]\s*'?\s*20\d{2}|"
    # NB: bare "may" is omitted (modal-verb collision, e.g. "adoption may slow");
    # "May 2027"-style dates are still caught by the 20\d{2} year alternative.
    r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|jun(e)?|jul(y)?|aug(ust)?|"
    r"sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?|"
    r"within\s+\d+\s+(day|week|month|quarter|year)s?|by\s+(year[- ]?end|end[- ]of))\b",
    re.IGNORECASE,
)
_THRESH_RE = re.compile(
    r"([<>≥≤]=?|more than|less than|at least|at most|above|below|exceeds?|under|over|fewer than)"
    r"\s*[$€£¥]?\s*\d"
    r"|[$€£¥]\s?\d"
    r"|\d[\d,]*(\.\d+)?\s*(%|percent|bn|billion|mn|million|k|thousand|x)\b",
    re.IGNORECASE,
)


def check_falsifiers(read: dict) -> dict:
    """Mechanical rubric criteria only: 2 (time-bound) + 4 (threshold), 0/2 each.
    Specificity / refutation / checkability / non-triviality need the LLM panel."""
    per_signal, missing, undated, no_threshold = [], [], [], []
    for i, sig in enumerate(read.get("signals") or [], 1):
        f = str(sig.get("falsifier") or "").strip()
        present = bool(f)
        has_date = bool(_DATE_RE.search(f)) if present else False
        has_threshold = bool(_THRESH_RE.search(f)) if present else False
        mech = (2 if has_date else 0) + (2 if has_threshold else 0)
        row = {"signal": i, "title": sig.get("title"), "falsifier": f, "present": present,
               "has_date": has_date, "has_threshold": has_threshold, "mech_score": mech}
        per_signal.append(row)
        if not present:
            missing.append(row)
        else:
            if not has_date:
                undated.append(row)
            if not has_threshold:
                no_threshold.append(row)
    mean = sum(r["mech_score"] for r in per_signal) / len(per_signal) if per_signal else 0.0
    return {"per_signal": per_signal, "mean_mech": round(mean, 2),
            "missing": missing, "undated": undated, "no_threshold": no_threshold}


# ═════════════════════════════════════════════════════════════════════════════
# 4. Overclaim lexicon + evidence-strength heuristic
# ═════════════════════════════════════════════════════════════════════════════

# Assertive/settled verbs the mot_scholar rubric docks unless evidence warrants.
# NOTE: "locks in / locking in" is deliberately absent — it is the sanctioned
# lens vocabulary ("Dominant design locking in"), not an overclaim by itself.
OVERCLAIM_TERMS = (
    "wins", "has won", "confirms", "confirmed", "proves", "proven",
    "guarantees", "guaranteed", "inevitable", "inevitably", "certain to",
    "certainly", "undoubtedly", "definitively", "will dominate", "assures",
    "cements", "game over", "settles", "unquestionably", "unstoppable",
)
_OVERCLAIM_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in OVERCLAIM_TERMS) + r")\b", re.IGNORECASE
)
# Falsifier excluded: it states a hypothetical ("Samsung WINS >20%..."), not a claim.
_OVERCLAIM_FIELDS = ("title", "implication", "action_rationale", "value_capture")


def check_overclaims(read: dict, stories: list[dict]) -> dict:
    """A lexicon hit is a VIOLATION unless evidence is strong: stated confidence
    'high' AND >=2 distinct valid cited sources (the rubric's corroboration bar)."""
    s_labels = {s.get("label") for s in stories}
    signals = read.get("signals") or []
    flagged, violations = [], []
    for i, sig in enumerate(signals, 1):
        text = " ".join(str(sig.get(f) or "") for f in _OVERCLAIM_FIELDS)
        terms = sorted({t.lower() for t in _OVERCLAIM_RE.findall(text)})
        if not terms:
            continue
        n_sources = len({r for r in (sig.get("sources") or []) if r in s_labels})
        strong = sig.get("confidence") == "high" and n_sources >= 2
        row = {"signal": i, "title": sig.get("title"), "terms": terms,
               "confidence": sig.get("confidence"), "valid_sources": n_sources,
               "evidence_strong": strong}
        flagged.append(row)
        if not strong:
            violations.append(row)
    rate = 100.0 * len(violations) / len(signals) if signals else 0.0
    return {"flagged": flagged, "violations": violations, "rate": round(rate, 1)}


# ═════════════════════════════════════════════════════════════════════════════
# Deterministic scorecard
# ═════════════════════════════════════════════════════════════════════════════

def run_deterministic(brief: dict) -> dict:
    read = brief.get("strategic_read") or {}
    if read.get("format") != "structured" or not read.get("signals"):
        raise ValueError("Brief is not a structured read with signals — nothing to judge.")
    stories = brief.get("stories") or []
    theory = brief.get("theory") or []

    grounding = check_grounding(read, stories)
    sref = check_references(read, stories, theory)
    falsifier = check_falsifiers(read)
    overclaim = check_overclaims(read, stories)

    passes = {
        "grounding_pct_ge_95": grounding["pct"] >= TARGET_GROUNDING_PCT,
        "zero_hallucinated_numbers": not grounding["hallucinated"],
        "sref_100pct_valid": sref["pct"] >= TARGET_SREF_PCT,
        "all_falsifiers_present": not falsifier["missing"],
        "falsifier_mech_mean_ge_3of4": falsifier["mean_mech"] >= TARGET_FALSIFIER_MECH,
        "overclaim_rate_le_10pct": overclaim["rate"] <= TARGET_OVERCLAIM_PCT,
    }
    return {
        "as_of": brief.get("as_of"), "focus": brief.get("focus"),
        "signals_n": len(read["signals"]),
        "grounding": grounding, "sref": sref, "falsifier": falsifier,
        "overclaim": overclaim, "passes": passes, "all_pass": all(passes.values()),
    }


def render_scorecard(sc: dict) -> str:
    g, r, f, o = sc["grounding"], sc["sref"], sc["falsifier"], sc["overclaim"]
    ln = [
        f"L8 Strategist — deterministic scorecard (as_of={sc['as_of']}, focus={sc['focus']}, "
        f"signals={sc['signals_n']})",
        "",
        f"  Grounding        : {g['pct']}%  ({g['grounded']}/{g['hard_claims']} hard numeric "
        f"claims in cited sources; target >=95% & 0 hallucinated)",
    ]
    for h in g["hallucinated"]:
        ln.append(f"    HALLUCINATED   : signal {h['signal']} \"{h['title']}\" — '{h['claim']}' "
                  f"appears in NO source")
    for m in g["misattributed"]:
        ln.append(f"    misattributed  : signal {m['signal']} — '{m['claim']}' found only in "
                  f"sources the signal did not cite")
    for a in g["advisory_unmatched"]:
        ln.append(f"    advisory       : signal {a['signal']} — '{a['claim']}' (year/small count) "
                  f"unmatched; not counted")
    ln.append(f"  S#/T# validity   : {r['pct']}%  ({r['valid']}/{r['refs']} refs resolve; "
              f"target 100%)")
    for p in r["phantom"]:
        ln.append(f"    PHANTOM REF    : signal {p['signal']} \"{p['title']}\" cites {p['ref']} "
                  f"— no such item in the brief's source set")
    for s in r["signals_without_sources"]:
        ln.append(f"    NO SOURCES     : signal {s['signal']} \"{s['title']}\" has an empty "
                  f"sources[] (contract requires >=1)")
    ln.append(f"  Falsifier (mech) : mean {f['mean_mech']}/4  (dated 0/2 + threshold 0/2; "
              f"full /12 needs the LLM panel)")
    for row in f["per_signal"]:
        flags = []
        if not row["present"]:
            flags.append("MISSING")
        else:
            if not row["has_date"]:
                flags.append("UNDATED")
            if not row["has_threshold"]:
                flags.append("NO THRESHOLD")
        tail = f"  <- {', '.join(flags)}" if flags else ""
        ln.append(f"    signal {row['signal']}: {row['mech_score']}/4 — "
                  f"\"{(row['falsifier'] or '(none)')[:80]}\"{tail}")
    ln.append(f"  Overclaim rate   : {o['rate']}%  ({len(o['violations'])}/{sc['signals_n']} "
              f"signals; target <=10%)")
    for v in o["violations"]:
        ln.append(f"    OVERCLAIM      : signal {v['signal']} \"{v['title']}\" uses "
                  f"{v['terms']} with confidence={v['confidence']}, "
                  f"{v['valid_sources']} valid source(s) — evidence too weak")
    for fl in o["flagged"]:
        if fl["evidence_strong"]:
            ln.append(f"    (allowed)      : signal {fl['signal']} uses {fl['terms']} but "
                      f"evidence is strong (high confidence, >=2 sources)")
    ln.append("")
    verdict = "PASS" if sc["all_pass"] else "FAIL"
    failed = [k for k, v in sc["passes"].items() if not v]
    ln.append(f"  VERDICT: {verdict}" + (f" — failed: {', '.join(failed)}" if failed else
                                         " — all deterministic L8 targets met"))
    return "\n".join(ln)


# ═════════════════════════════════════════════════════════════════════════════
# LLM-judge panel (GATED — never runs without --live-judge AND explicit creds)
# ═════════════════════════════════════════════════════════════════════════════

SCHOLAR_JUDGE_PROMPT = """\
You are Judge #{judge_id} of {panel_size} on an evaluation panel for "the Strategist",
a Management-of-Technology (MOT) analyst. Judge ONE signal from its briefing,
strictly against the two rubrics below. Be independent: do not assume other
judges' views. Score ONLY from the evidence in the cited sources — the framework's
preconditions must be EVIDENCED there, not asserted.

=== RUBRIC 1: MOT THEORY FIDELITY (score 0-3) ===
{mot_rubric}

=== RUBRIC 2: FALSIFIER QUALITY (six criteria, 0/1/2 each, total /12) ===
{falsifier_rubric}

=== THE SIGNAL UNDER JUDGMENT ===
{signal_json}

=== THE SOURCES THE SIGNAL CITES ===
{sources_block}

=== THEORY PASSAGES AVAILABLE TO THE STRATEGIST ===
{theory_block}

Return ONLY a JSON object, no prose:
{{"theory_fidelity": 0-3,
  "misapplication": true/false,
  "misapplication_note": "which framework is misapplied and why, or empty",
  "discriminator": "the one observation that decided your fidelity score",
  "falsifier_scores": {{"specific": 0-2, "time_bound": 0-2, "refuting": 0-2,
                        "threshold": 0-2, "checkable": 0-2, "non_trivial": 0-2}},
  "falsifier_total": 0-12,
  "overclaim": true/false,
  "notes": "one sentence"}}
"""

REFUTER_JUDGE_PROMPT = """\
You are Judge #{judge_id} of {panel_size} — the ADVERSARIAL judge. Your explicit job
is to REFUTE this signal: hunt for the strongest case that the framework is
misapplied, the preconditions are NOT evidenced in the cited sources, the numbers
do not trace, the falsifier would not actually refute the call, or the confidence
is overclaimed. Steelman the refutation FIRST; concede only what survives it.
Score strictly against the same two rubrics — if your refutation holds, the
scores must reflect it.

=== RUBRIC 1: MOT THEORY FIDELITY (score 0-3) ===
{mot_rubric}

=== RUBRIC 2: FALSIFIER QUALITY (six criteria, 0/1/2 each, total /12) ===
{falsifier_rubric}

=== THE SIGNAL UNDER JUDGMENT ===
{signal_json}

=== THE SOURCES THE SIGNAL CITES ===
{sources_block}

=== THEORY PASSAGES AVAILABLE TO THE STRATEGIST ===
{theory_block}

Return ONLY a JSON object in exactly this shape (refutation first):
{{"strongest_refutation": "1-2 sentences: the best case this signal is wrong/misapplied",
  "refutation_survives": true/false,
  "theory_fidelity": 0-3,
  "misapplication": true/false,
  "misapplication_note": "which framework is misapplied and why, or empty",
  "falsifier_scores": {{"specific": 0-2, "time_bound": 0-2, "refuting": 0-2,
                        "threshold": 0-2, "checkable": 0-2, "non_trivial": 0-2}},
  "falsifier_total": 0-12,
  "overclaim": true/false,
  "notes": "one sentence"}}
"""


def _load_rubrics() -> tuple[str, str]:
    return (
        (RUBRIC_DIR / "mot_scholar.md").read_text(encoding="utf-8"),
        (RUBRIC_DIR / "falsifier.md").read_text(encoding="utf-8"),
    )


def build_judge_prompts(brief: dict) -> list[dict]:
    """All (signal x judge) prompts for the panel — pure, safe to call offline
    (e.g. to inspect or count the calls a live run would make)."""
    mot_rubric, falsifier_rubric = _load_rubrics()
    read = brief.get("strategic_read") or {}
    stories = {s.get("label"): s for s in (brief.get("stories") or [])}
    theory_block = "\n".join(
        f"[{t.get('label')}] {t.get('source_file')}: {t.get('chunk_text', '')[:500]}"
        for t in (brief.get("theory") or [])
    ) or "(none retrieved)"
    prompts = []
    for i, sig in enumerate(read.get("signals") or [], 1):
        cited = [stories[r] for r in (sig.get("sources") or []) if r in stories]
        sources_block = "\n".join(
            f"[{s.get('label')}] {s.get('title')} (src={s.get('source_name')}, "
            f"date={s.get('published_at')})\n    {s.get('summary')}"
            for s in cited
        ) or "(the signal cites no resolvable sources — judge accordingly)"
        for judge_id in range(1, PANEL_SIZE + 1):
            tmpl = REFUTER_JUDGE_PROMPT if judge_id == PANEL_SIZE else SCHOLAR_JUDGE_PROMPT
            prompts.append({
                "signal": i, "judge": judge_id,
                "role": "refuter" if judge_id == PANEL_SIZE else "scholar",
                "prompt": tmpl.format(
                    judge_id=judge_id, panel_size=PANEL_SIZE,
                    mot_rubric=mot_rubric, falsifier_rubric=falsifier_rubric,
                    signal_json=json.dumps(sig, indent=2, ensure_ascii=False),
                    sources_block=sources_block, theory_block=theory_block,
                ),
            })
    return prompts


def aggregate_panel(votes_by_signal: dict[int, list[dict]]) -> dict:
    """Majority rules: median fidelity + falsifier total per signal;
    misapplication/overclaim stand only if >=2 of 3 judges flag them."""
    per_signal, fid_means, fals_means = [], [], []
    for i, votes in sorted(votes_by_signal.items()):
        fid = median(v.get("theory_fidelity", 0) for v in votes)
        fal = median(v.get("falsifier_total", 0) for v in votes)
        mis = sum(1 for v in votes if v.get("misapplication")) >= 2
        ovc = sum(1 for v in votes if v.get("overclaim")) >= 2
        non_refuting = sum(
            1 for v in votes if (v.get("falsifier_scores") or {}).get("refuting", 2) == 0
        ) >= 2
        per_signal.append({"signal": i, "theory_fidelity": fid, "falsifier_total": fal,
                           "misapplication": mis, "overclaim": ovc,
                           "falsifier_non_refuting": non_refuting, "votes": votes})
        fid_means.append(fid)
        fals_means.append(fal)
    return {
        "per_signal": per_signal,
        "theory_fidelity_mean": round(sum(fid_means) / len(fid_means), 2) if fid_means else None,
        "falsifier_mean": round(sum(fals_means) / len(fals_means), 2) if fals_means else None,
        "misapplications": [s["signal"] for s in per_signal if s["misapplication"]],
        "non_refuting_falsifiers": [s["signal"] for s in per_signal if s["falsifier_non_refuting"]],
    }


def run_live_panel(brief: dict) -> dict:
    """GATED. Runs signals x 3 Toqan judge calls. Requires an explicit judge key
    (TOQAN_JUDGE) — refuses otherwise. Mirrors the ToqanAgent wiring used by
    analytics/strategist.py and lens_ab.py; imports are lazy so the offline
    path never touches network code."""
    import os

    prompts = build_judge_prompts(brief)
    api_key = os.getenv(ENV_KEY_JUDGE)
    if not api_key:
        raise RuntimeError(
            f"NEEDS APPROVAL: live judge panel would make {len(prompts)} Toqan calls "
            f"({len(prompts) // PANEL_SIZE} signals x {PANEL_SIZE} judges). "
            f"Set {ENV_KEY_JUDGE} and get explicit user sign-off before running. "
            "Offline deterministic checks ran/are available without it."
        )
    from toqan.client import ToqanAgent          # noqa: lazy — network code
    from toqan.json_utils import parse_json_object

    agent = ToqanAgent(api_key=api_key, agent_name="Strategist Judge")
    votes: dict[int, list[dict]] = {}
    for p in prompts:
        raw = agent.ask(p["prompt"])
        obj = parse_json_object(raw)
        if not isinstance(obj, dict):
            obj = {"theory_fidelity": 0, "falsifier_total": 0,
                   "misapplication": True, "notes": f"unparseable judge answer: {raw[:120]}"}
        obj["_role"] = p["role"]
        votes.setdefault(p["signal"], []).append(obj)
    return aggregate_panel(votes)


# ═════════════════════════════════════════════════════════════════════════════
# Input modes + CLI
# ═════════════════════════════════════════════════════════════════════════════

def load_from_fixture(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_from_supabase(focus: str = "daily") -> dict:
    """Latest stored brief for `focus` from the production strategist_briefs
    table. READ-ONLY: a single SELECT via db.get_supabase(); never writes.
    The row embeds its slimmed S#/T# source sets (analytics/strategist.py
    stores them alongside strategic_read), so grounding is auditable offline.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from db import get_supabase  # lazy: only the supabase path needs creds

    resp = (
        get_supabase()
        .table("strategist_briefs")
        .select("*")
        .eq("focus", focus)
        .order("as_of", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise RuntimeError(f"strategist_briefs has no row for focus={focus!r}.")
    return rows[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="L8 Strategist judge harness — deterministic checks + gated LLM panel.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-fixture", metavar="PATH",
                     help="stored brief JSON (strategist_briefs row shape) — offline")
    src.add_argument("--from-supabase", action="store_true",
                     help="latest live brief from strategist_briefs (SELECT-only)")
    ap.add_argument("--focus", default="daily", help="brief focus for --from-supabase")
    ap.add_argument("--live-judge", action="store_true",
                    help=f"run the {PANEL_SIZE}-judge Toqan panel (GATED: needs "
                         f"{ENV_KEY_JUDGE} + explicit approval)")
    ap.add_argument("--json", action="store_true", help="emit the scorecard as JSON")
    args = ap.parse_args(argv)

    try:
        brief = load_from_supabase(args.focus) if args.from_supabase \
            else load_from_fixture(args.from_fixture)
    except RuntimeError as e:  # the --from-supabase stub
        print(f"error: {e}", file=sys.stderr)
        return 2

    sc = run_deterministic(brief)

    if args.live_judge:
        try:
            sc["panel"] = run_live_panel(brief)
        except RuntimeError as e:  # gated: no judge creds / no approval
            print(render_scorecard(sc))
            print(f"\nerror: {e}", file=sys.stderr)
            return 2
    else:
        n_calls = len(build_judge_prompts(brief))
        sc["panel"] = None
        sc["panel_note"] = (f"LLM panel not run (pass --live-judge; would make "
                            f"{n_calls} Toqan calls = {sc['signals_n']} signals x "
                            f"{PANEL_SIZE} judges; NEEDS APPROVAL)")

    if args.json:
        print(json.dumps(sc, indent=2, ensure_ascii=False))
    else:
        print(render_scorecard(sc))
        if sc.get("panel_note"):
            print(f"\n  {sc['panel_note']}")
        if sc.get("panel"):
            p = sc["panel"]
            print(f"\n  LLM panel: theory fidelity mean {p['theory_fidelity_mean']}/3 "
                  f"(target >=2.0, 0 misapplications), falsifier mean "
                  f"{p['falsifier_mean']}/12 (target >=9)")
    return 0 if sc["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
