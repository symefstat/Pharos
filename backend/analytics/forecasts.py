"""
Forecast ledger — accountable predictions, not vibes.

Every forecast is **falsifiable** (an explicit resolution criterion + a resolve-by
date), **locked** once made (fingerprinted for idempotent logging — no retroactive
edits), and **resolved objectively**: automatically against our own data where the
claim is machine-checkable (a technology advancing an adoption stage, a sector
keeping its capital tilt, deal-flow continuing), and manually for the judgment
calls captured from the Strategist. Scoring is calibration-first — accuracy +
Brier score + a calibration curve — per MOT Section G (epistemic rigour).

Pure: generation, resolution, and scoring are all pure functions over data the
`forecast_run` job fetches. No network, no Streamlit, no clock (the job passes
`as_of`), so every path is unit-testable.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd

ADOPTION_ORDER = ["innovators", "early-adopters", "early-majority", "late-majority", "laggards"]
MATURITY_ORDER = ["research", "emerging", "growth", "dominant-design", "mature", "declining"]
_CONF = {"high": 0.75, "medium": 0.55, "low": 0.4}
HORIZON_DAYS = {"short": 90, "long": 540}
_OUTCOME_VALUE = {"hit": 1.0, "partial": 0.5, "miss": 0.0}


def _to_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _idx(stage) -> int | None:
    try:
        return ADOPTION_ORDER.index(stage)
    except (ValueError, TypeError):
        return None


def _midx(stage) -> int | None:
    try:
        return MATURITY_ORDER.index(stage)
    except (ValueError, TypeError):
        return None


def _fp(basis: str) -> str:
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


# Words that carry no claim identity — kept tiny on purpose; the 5-char prefix
# stem below already collapses inflections (token/tokenization, force/forces).
_CLAIM_STOP = frozenset(
    "a an and as at by for from in into of on or over past the to with wrong if".split()
)


def _claim_tokens(claim: str) -> frozenset:
    """Content-word shingle of a claim, ignoring any '— wrong if:' falsifier tail
    (the same call is often re-emitted with a reworded falsifier). Pure."""
    head = re.split(r"—\s*wrong if", claim or "", flags=re.IGNORECASE)[0].lower()
    words = re.findall(r"[a-z0-9]+", head)
    return frozenset(w[:5] for w in words if w not in _CLAIM_STOP)


def claims_similar(a: str, b: str, threshold: float = 0.5) -> bool:
    """True if two forecast claims are near-paraphrases of the same call.

    Fingerprints only catch byte-identical re-emissions; consecutive Strategist
    runs re-state the same judgment call with reworded text, and a duplicate open
    call double-counts in the track record once resolved. Token-Jaccard over
    prefix-stemmed content words is deliberately crude but pure and dependable:
    paraphrased re-emissions score well above 0.5, distinct claims about the same
    subject well below. Pure (unit-tested)."""
    ta, tb = _claim_tokens(a), _claim_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def _mk(*, kind, subject, claim, horizon, confidence, basis, params, as_of,
        fp_basis, source="quant", resolve_days=None) -> dict:
    # `resolve_days` pins resolve_by to the claim's actual window (e.g. ~1 month for
    # deal-flow) instead of the coarse short/long horizon bucket — so the resolve-by
    # date matches what the claim text promises.
    made = _to_date(as_of)
    days = resolve_days if resolve_days is not None else HORIZON_DAYS.get(horizon, 90)
    resolve_by = (made + timedelta(days=days)).isoformat()
    return {
        "fingerprint": _fp(fp_basis),
        "claim": claim,
        "kind": kind,
        "subject": subject,
        "horizon": horizon,
        "source": source,
        "confidence": round(float(confidence), 2),
        "basis": basis,
        "params": params,
        "made_on": made.isoformat(),
        "resolve_by": resolve_by,
        "status": "open",
        "outcome": None,
        "resolved_on": None,
        "resolution_note": None,
    }


# ── generation (pure) ─────────────────────────────────────────────────────────
def gen_stage_advance(placements, as_of, min_articles: int = 4) -> list[dict]:
    """Techs with room to advance + real coverage → predict they move ≥1 adoption
    stage within ~2 quarters. Auto-resolvable against stage history."""
    out = []
    for p in placements:
        adoption = p.get("adoption")
        i = _idx(adoption)
        if i is None or i >= len(ADOPTION_ORDER) - 1:
            continue
        if (p.get("articles") or 0) < min_articles:
            continue
        conf = round(0.5 + min(0.2, (p.get("articles") or 0) / 60.0), 2)
        out.append(_mk(
            kind="stage_advance", subject=p.get("tech"),
            claim=(f"{p.get('label')} advances beyond "
                   f"‘{adoption.replace('-', ' ')}’ adoption (≥1 stage) within ~2 quarters"),
            horizon="short", confidence=conf,
            basis=f"adoption={adoption}, {p.get('articles')} articles",
            params={"dimension": "adoption", "from_stage": adoption, "from_index": i,
                    "label": p.get("label")},
            as_of=as_of, resolve_days=180,          # claim is "within ~2 quarters"
            fp_basis=f"stage_advance|{p.get('tech')}|{_to_date(as_of)}"))
    return out


def gen_stage_advance_tech(placements, as_of, max_forecasts: int = 6,
                           min_articles: int = 6, min_upside: float = 0.25) -> list[dict]:
    """Anchor-grounded maturity-transition forecasts. A candidate is a technology
    whose ANCHORED display stage (committed_stage — the anchor-floored stage every
    surface shows) sits near the next boundary: a real share of its classified
    coverage already reads LATER than the displayed stage (`upside_share`). An
    anchored-above-news tech has no upside by construction, so news noise below the
    anchor floor never spawns a forecast — an advance here means the anchored
    display stage itself moves.

    Confidence is an evidence heuristic (upside share + coverage, docked when the
    placement is contested), NOT a constant — so calibration is measurable. Ranked
    by upside and capped at `max_forecasts` per run; the job's (kind, subject)
    open-forecast dedupe + fingerprint discipline prevent duplicates. Resolution:
    resolve_stage_advance_tech (confirmed display-stage advance in
    technology_stage_history). Pure."""
    cands = []
    for p in placements:
        if p.get("lifecycle_fit") is False:
            continue                              # tracked name, not a technology
        cur = p.get("committed_stage") or p.get("maturity")
        i = _midx(cur)
        if i is None or i >= MATURITY_ORDER.index("mature"):
            continue                              # only real advances (…→mature)
        n = p.get("stage_articles") or p.get("articles") or 0
        if n < min_articles:
            continue
        dist = p.get("stage_dist") or {}
        total = sum(dist.values())
        if not total:
            continue
        upside = sum(c for s, c in dist.items()
                     if (j := _midx(s)) is not None and j > i) / total
        if upside < min_upside:
            continue                              # not near the boundary
        conf = 0.35 + 0.35 * upside + min(0.1, n / 100.0)
        if p.get("mixed"):
            conf -= 0.05                          # contested placement → less conviction
        conf = round(max(0.35, min(0.8, conf)), 2)
        cands.append((upside, n, conf, i, cur, p))
    cands.sort(key=lambda c: (-c[0], -c[1]))      # strongest boundary signal first
    out = []
    for upside, n, conf, i, cur, p in cands[:max_forecasts]:
        to_stage = MATURITY_ORDER[i + 1]
        out.append(_mk(
            kind="stage_advance_tech", subject=p.get("tech"),
            claim=(f"{p.get('label')} advances maturity from ‘{cur}’ to ‘{to_stage}’ "
                   "(anchored display stage, confirmed) within ~1 quarter"),
            horizon="short", confidence=conf,
            basis=(f"display ‘{cur}’; {int(round(upside * 100))}% of classified coverage "
                   f"already reads later · {n} articles"
                   + (" · contested placement" if p.get("mixed") else "")),
            params={"dimension": "maturity", "from_stage": cur, "from_index": i,
                    "to_stage": to_stage, "to_index": i + 1,
                    "upside_share": round(upside, 3), "label": p.get("label")},
            as_of=as_of, resolve_days=90,           # claim is "within ~1 quarter"
            fp_basis=f"stage_advance_tech|{p.get('tech')}|{_to_date(as_of)}"))
    return out


def gen_posture_persist(sector_rollup, as_of) -> list[dict]:
    """Each sector with a clear commitment/option tilt → predict it persists next
    quarter. Auto-resolvable by recomputing posture later."""
    out = []
    for r in sector_rollup:
        c, o = r.get("commitment", 0), r.get("option", 0)
        if c + o < 2:
            continue
        tilt = "commitment" if c > o else "option" if o > c else None
        if not tilt:
            continue
        out.append(_mk(
            kind="posture_persist", subject=r.get("sector"),
            claim=f"{r.get('sector')} capital stays {tilt}-tilted through next quarter",
            horizon="short", confidence=0.55,
            basis=f"deals {c}:{o} — {tilt}-tilted now",
            params={"tilt": tilt}, as_of=as_of,
            fp_basis=f"posture_persist|{r.get('sector')}|{_to_date(as_of)}"))
    return out


# ── threshold calibration (pure) ───────────────────────────────────────────────
# The L7 eval showed the fixed deal-flow/reactivity thresholds produce ~100% base
# rates — every forecast hits, so Brier skill is unmeasurable (climatology Brier 0,
# "no test"). Fix: at GENERATION time, pick each sector's threshold from its own
# trailing windows so the event lands in the ~50–70% band, and lock the chosen
# threshold + its basis into the new forecast's params/claim (resolution reads the
# locked params, so old rows are untouched and grading stays objective).
DEAL_FLOW_THRESHOLD = 2          # floor + thin-history fallback (the old constant)
REACTIVITY_THRESHOLD_PCT = 2.0   # floor + thin-history fallback (the old constant)
DEAL_FLOW_THRESHOLD_CAP = 10
REACTIVITY_THRESHOLD_CAP = 8.0
CALIBRATION_TARGET = 0.6         # aim the base rate at ~60% (inside 50–70%)
MIN_CALIBRATION_WINDOWS = 8      # fewer trailing windows than this → fall back


def threshold_for_target_rate(values, target: float = CALIBRATION_TARGET) -> float | None:
    """The largest threshold t such that the event `value ≥ t` occurred in at least
    `target` share of the observed windows — i.e. the (1−target) quantile of the
    per-window values. Deterministic given inputs; None on empty input. Pure."""
    vals = sorted((float(v) for v in values), reverse=True)
    if not vals:
        return None
    k = max(1, math.ceil(target * len(vals)))
    return vals[min(k, len(vals)) - 1]


def _window_ends(as_of, earliest, window_days: int, max_windows: int = 60) -> list[date]:
    """Daily-stepped rolling-window end dates, newest first: every day e ≤ as_of whose
    full (e−window_days, e] window is covered by the fetched history (≥ earliest).
    Overlapping by design — a deterministic percentile estimate, not an i.i.d. sample."""
    a, e0 = _to_date(as_of), _to_date(earliest)
    if not a or not e0:
        return []
    ends, e = [], a
    while e - timedelta(days=window_days) >= e0 and len(ends) < max_windows:
        ends.append(e)
        e -= timedelta(days=1)
    return ends


def earliest_published(rows) -> str | None:
    """Earliest published_at date across the fetched feed rows — the honest start of
    the trailing history (feeds prune, so the requested fetch span may not exist)."""
    ds = [d for r in (rows or []) if (d := _to_date(str(r.get("published_at") or "")[:10]))]
    return min(ds).isoformat() if ds else None


def sector_deal_dates(rows, ticker_for) -> dict:
    """Dated material capital deals per sector (same filter as sector_deal_counts) —
    the trailing history the deal-flow threshold calibration reads. Pure."""
    from analytics.mot_analyst import _is_capital_row

    out: dict = {}
    for r in rows:
        if str(r.get("business_impact") or "").lower() != "material" or not _is_capital_row(r):
            continue
        d = str(r.get("published_at") or "")[:10]
        if not _to_date(d):
            continue
        secs = {tk.sector for comp in (r.get("companies") or []) if (tk := ticker_for(str(comp)))}
        for s in secs:
            out.setdefault(s, []).append(d)
    return out


def sector_reaction_moves(reactions, ticker_for) -> dict:
    """Per-sector dated |price-move| observations from the measured deal reactions
    (financials.deal_reactions output) — the trailing history the reactivity
    threshold calibration reads. Pure."""
    out: dict = {}
    for rx in (reactions or []):
        tk = ticker_for(str(rx.get("company") or ""))
        d = str(rx.get("event_date") or "")[:10]
        if not tk or rx.get("pct") is None or not _to_date(d):
            continue
        out.setdefault(tk.sector, []).append((d, float(rx["pct"])))
    return out


def _calibration_basis(n_windows: int, window_days: int,
                       target: float = CALIBRATION_TARGET) -> str:
    return (f"calibrated-p{int(round(target * 100))} "
            f"(trailing {n_windows} × {window_days}d windows)")


def deal_flow_calibration(deal_dates_by_sector: dict, as_of, earliest, *,
                          window_days: int = 30, target: float = CALIBRATION_TARGET,
                          floor: int = DEAL_FLOW_THRESHOLD,
                          cap: int = DEAL_FLOW_THRESHOLD_CAP,
                          min_windows: int = MIN_CALIBRATION_WINDOWS) -> dict:
    """Per-sector calibrated deal-count threshold: the count N such that '≥N material
    deals in a 30d window' held in ~`target` of the trailing windows. Clamped to
    [floor, cap]; falls back to the old constant (marked as such) when the trailing
    history is thin. Returns {sector: {'threshold': int, 'basis': str}}. Pure."""
    ends = _window_ends(as_of, earliest, window_days)
    out = {}
    for sector, dates in (deal_dates_by_sector or {}).items():
        if len(ends) < min_windows:
            out[sector] = {"threshold": int(floor),
                           "basis": f"default (thin history: {len(ends)} windows "
                                    f"< {min_windows})"}
            continue
        ds = [d for d in (_to_date(x) for x in dates) if d]
        counts = [sum(1 for d in ds if e - timedelta(days=window_days) < d <= e)
                  for e in ends]
        t = threshold_for_target_rate(counts, target)
        out[sector] = {"threshold": int(max(floor, min(cap, int(t)))),
                       "basis": _calibration_basis(len(ends), window_days, target)}
    return out


def reactivity_calibration(moves_by_sector: dict, as_of, earliest, *,
                           window_days: int = 30, target: float = CALIBRATION_TARGET,
                           floor: float = REACTIVITY_THRESHOLD_PCT,
                           cap: float = REACTIVITY_THRESHOLD_CAP,
                           min_windows: int = MIN_CALIBRATION_WINDOWS) -> dict:
    """Per-sector calibrated reactivity threshold: the move X% such that '≥1 deal
    moved the stock ≥X% in a 30d window' held in ~`target` of the trailing windows
    (per-window statistic = max |move|, 0 when no deal was priced). Clamped to
    [floor, cap]; thin history falls back to the old constant, marked. Returns
    {sector: {'threshold_pct': float, 'basis': str}}. Pure."""
    ends = _window_ends(as_of, earliest, window_days)
    out = {}
    for sector, moves in (moves_by_sector or {}).items():
        if len(ends) < min_windows:
            out[sector] = {"threshold_pct": float(floor),
                           "basis": f"default (thin history: {len(ends)} windows "
                                    f"< {min_windows})"}
            continue
        parsed = [(d, abs(float(p))) for x, p in moves if (d := _to_date(x))]
        maxima = [max((p for d, p in parsed
                       if e - timedelta(days=window_days) < d <= e), default=0.0)
                  for e in ends]
        t = threshold_for_target_rate(maxima, target)
        out[sector] = {"threshold_pct": round(max(floor, min(cap, float(t))), 1),
                       "basis": _calibration_basis(len(ends), window_days, target)}
    return out


def gen_deal_flow(sector_deal_counts: dict, as_of, threshold: int = 2,
                  calibration: dict | None = None) -> list[dict]:
    """Sectors already active on deals → predict ≥threshold more material deals
    within ~1 month. Auto-resolvable by counting later. `calibration` (from
    deal_flow_calibration) overrides the fixed threshold per sector; the chosen
    threshold + basis are locked into the forecast's params/claim at creation."""
    out = []
    for sector, n in sector_deal_counts.items():
        cal = (calibration or {}).get(sector) or {}
        thr = int(cal.get("threshold", threshold))
        basis_note = cal.get("basis", "fixed default")
        if (n or 0) < thr:
            continue
        out.append(_mk(
            kind="deal_flow", subject=sector,
            claim=f"{sector} sees ≥{thr} more material deals within ~1 month",
            horizon="short", confidence=0.6,
            basis=f"{n} material deals in the last 30d · threshold {basis_note}",
            params={"threshold": thr, "window_days": 30, "threshold_basis": basis_note},
            as_of=as_of,
            resolve_days=30,                        # claim is "within ~1 month"
            fp_basis=f"deal_flow|{sector}|{_to_date(as_of)}"))
    return out


def gen_reactivity(sector_deal_counts: dict, as_of, threshold_pct: float = 2.0,
                   calibration: dict | None = None) -> list[dict]:
    """Honest 'about the market' forecast: in sectors with deal activity, predict
    the market *reacts* — ≥1 material deal moves the stock ≥threshold% (3-day)
    within ~1 month. About whether the market moves, NOT which direction.
    Auto-resolved via our event study. `calibration` (from reactivity_calibration)
    overrides the fixed threshold per sector; threshold + basis are locked in."""
    out = []
    for sector, n in sector_deal_counts.items():
        if (n or 0) < 1:
            continue
        cal = (calibration or {}).get(sector) or {}
        thr = float(cal.get("threshold_pct", threshold_pct))
        basis_note = cal.get("basis", "fixed default")
        out.append(_mk(
            kind="reactivity", subject=sector,
            claim=(f"≥1 of {sector}'s material deals moves the stock ≥{thr:g}% "
                   "(3-day) within ~1 month"),
            horizon="short", confidence=0.6,
            basis=(f"{n} material deals in the last 30d; deals in this sector tend "
                   f"to be priced · threshold {basis_note}"),
            params={"threshold_pct": thr, "window_days": 30, "threshold_basis": basis_note},
            as_of=as_of,
            resolve_days=30,                        # claim is "within ~1 month"
            fp_basis=f"reactivity|{sector}|{_to_date(as_of)}"))
    return out


def gen_price_move(prices_by_symbol: dict, symbol_entity: dict, as_of,
                   lookback: int = 30, threshold: float = 5.0, top: int = 8) -> list[dict]:
    """Price-DIRECTION calls (momentum continuation) — deliberately low-signal.
    Short-horizon prices are ~efficient, so confidence is pinned at 0.50: we're
    forecasting our own ignorance, and the calibration record will expose whether
    these beat a coin flip. Capped to the `top` strongest movers so these don't
    swamp the higher-signal forecasts (the rest are skipped, not silently lost)."""
    cands = []
    for symbol, series in prices_by_symbol.items():
        if len(series) < lookback + 1:
            continue
        closes = [p["close"] for p in series]   # ascending
        recent, past = closes[-1], closes[-(lookback + 1)]
        if past <= 0:
            continue
        mom = (recent - past) / past * 100
        if abs(mom) < 3:                          # no clear move → not a real directional call
            continue
        cands.append((abs(mom), symbol, mom))
    cands.sort(reverse=True, key=lambda c: c[0])  # strongest movers first
    out = []
    for _, symbol, mom in cands[:top]:
        direction = "up" if mom > 0 else "down"
        entity = symbol_entity.get(symbol, symbol)
        out.append(_mk(
            kind="price_move", subject=symbol,
            claim=(f"{entity} stock continues {direction} (≥{threshold:.0f}% point-to-point in "
                   "90 days) — low-signal momentum call"),
            horizon="short", confidence=0.5,
            basis=f"30-day momentum {mom:+.0f}% · short-term prices are ~random, expect coin-flip",
            params={"symbol": symbol, "direction": direction, "threshold": threshold,
                    "entity": entity}, as_of=as_of,
            fp_basis=f"price_move|{symbol}|{_to_date(as_of)}"))
    return out


def sector_deal_counts(rows, ticker_for) -> dict:
    """Count *material* deal stories per sector (via the companies named), for the
    deal-flow generator and resolver. Pure."""
    from collections import Counter
    from analytics.mot_analyst import _is_capital_row

    c: Counter = Counter()
    for r in rows:
        if str(r.get("business_impact") or "").lower() != "material" or not _is_capital_row(r):
            continue
        secs = {tk.sector for comp in (r.get("companies") or []) if (tk := ticker_for(str(comp)))}
        for s in secs:
            c[s] += 1
    return dict(c)


def gen_from_strategist(brief: dict, as_of) -> list[dict]:
    """Capture each structured Strategist signal as a forecast (manual resolution).
    Falsifier becomes the resolution criterion; horizon/confidence carry over."""
    read = (brief or {}).get("strategic_read") or {}
    brief_as_of = (brief or {}).get("as_of") or str(_to_date(as_of))
    out = []
    for s in (read.get("signals") or []):
        title = s.get("title")
        if not title:
            continue
        fals = s.get("falsifier")
        horizon = "long" if str(s.get("horizon", "")).lower().startswith(("far", "long", "struct")) else "short"
        # Prefer the granular calibrated probability (prompt v3) over the coarse
        # label map — all-0.75/0.55 confidences leave the judgment-call
        # calibration plot with only two occupied bands.
        num = s.get("confidence_num")
        conf = num if isinstance(num, (int, float)) and 0 < num < 1 \
            else _CONF.get(str(s.get("confidence", "")).lower(), 0.55)
        claim = title + (f" — wrong if: {fals}" if fals else "")
        out.append(_mk(
            kind="manual", subject=(s.get("lens") or "signal"),
            claim=claim, horizon=horizon, confidence=conf,
            basis=f"Strategist {brief_as_of} · {s.get('lens') or '—'}",
            params={"falsifier": fals}, as_of=as_of, source="strategist",
            fp_basis=f"strategist|{brief_as_of}|{title}"))
    return out


# ── resolution (pure) ──────────────────────────────────────────────────────────
# Each returns (outcome, note) when decidable, or None to leave open. The job
# turns "still open + past resolve_by" into a miss for the auto kinds.
def resolve_stage_advance(pred, history_rows) -> tuple | None:
    """history_rows: stage-history snapshots (any techs). Hit as soon as the
    subject's adoption stage exceeds the from_index within the window."""
    from_i = (pred.get("params") or {}).get("from_index")
    if from_i is None:
        return None
    made, by = _to_date(pred.get("made_on")), _to_date(pred.get("resolve_by"))
    for h in history_rows:
        if h.get("technology") != pred.get("subject"):
            continue
        d = _to_date(h.get("as_of"))
        if not d or d <= made or d > by:          # strictly after made_on (not the made day)
            continue
        j = _idx(h.get("adoption_stage"))
        if j is not None and j > from_i:
            return ("hit", f"adoption reached ‘{h.get('adoption_stage')}’ by {d.isoformat()}")
    return None


def resolve_radar_detection(pred, history_rows, as_of) -> tuple | None:
    """Grade a Radar detection at its 90-day mark (pure): HIT if the promoted
    technology still clears the placement evidence floor then — i.e. the
    surfaced thing proved durable, not a news splash. Judged ONLY at/after
    resolve_by (the claim is about sustained relevance, not a fast start), on
    the latest stage-history snapshot inside the claim window. No snapshot in
    the window = coverage died = MISS."""
    from analytics.tech_layer import EVIDENCE_FLOOR

    made, by = _to_date(pred.get("made_on")), _to_date(pred.get("resolve_by"))
    now = _to_date(as_of)
    if not (made and by and now) or now < by:
        return None
    latest = None
    for h in history_rows:
        if h.get("technology") != pred.get("subject"):
            continue
        d = _to_date(h.get("as_of"))
        if not d or d <= made or d > by:
            continue
        if latest is None or d > _to_date(latest.get("as_of")):
            latest = h
    if latest is None:
        return ("miss", "no placement snapshot inside the 90-day window — coverage died")
    n = latest.get("article_count") or 0
    if latest.get("maturity_stage") and n >= EVIDENCE_FLOOR:
        return ("hit", f"still placed at ‘{latest.get('maturity_stage')}’ with "
                       f"{n} articles on {latest.get('as_of')} (floor {EVIDENCE_FLOOR})")
    return ("miss", f"below the evidence floor at the deadline "
                    f"({n} articles on {latest.get('as_of')}, floor {EVIDENCE_FLOOR})")


def resolve_stage_advance_tech(pred, history_rows) -> tuple | None:
    """Objective, anchored maturity-transition resolver over technology_stage_history
    (the snapshots persist the committed/anchored DISPLAY stage — the same stage the
    claim was made about).

    HIT only when the advance is CONFIRMED: ≥2 consecutive classified snapshots,
    dated strictly after made_on and at/before resolve_by, sit at/above the locked
    target stage with no contested reading — mirroring detect_transitions' debounce
    (confirmed = run ≥ 2) and contested (`maturity_mixed`) semantics, so a suspect
    one-snapshot flip or a mixed-spread placement never banks a hit. Unclassified
    snapshots are skipped (a coverage gap isn't a regression); a below-target or
    contested snapshot resets the confirmation run. Never returns a miss — the
    job's overdue backstop grades an unconfirmed advance MISS at resolve_by."""
    to_i = (pred.get("params") or {}).get("to_index")
    if to_i is None:
        return None
    made, by = _to_date(pred.get("made_on")), _to_date(pred.get("resolve_by"))
    snaps = sorted((h for h in (history_rows or [])
                    if h.get("technology") == pred.get("subject")),
                   key=lambda h: str(h.get("as_of") or ""))
    run = 0
    for h in snaps:
        d = _to_date(h.get("as_of"))
        if not d or (made and d <= made) or (by and d > by):
            continue                              # strictly after made_on, within window
        j = _midx(h.get("maturity_stage"))
        if j is None:
            continue                              # unclassified gap — don't reset the run
        if j >= to_i and not h.get("maturity_mixed"):
            run += 1
            if run >= 2:
                return ("hit", f"maturity ‘{h.get('maturity_stage')}’ held for 2 "
                               f"consecutive snapshots by {d.isoformat()}")
        else:
            run = 0                               # dip or contested reading — restart
    return None


def resolve_posture_persist(pred, current_tilt, as_of) -> tuple | None:
    """'Stays X-tilted through next quarter' is a DURATION claim — so it resolves to
    HIT only once `resolve_by` has elapsed and it's *still* X (you can't confirm
    persistence on day 0, when the tilt was just measured to make the call). A flip
    to a different tilt is a valid MISS at any time; otherwise it stays open.
    `current_tilt`: 'commitment' | 'option' | None (recomputed now)."""
    want = (pred.get("params") or {}).get("tilt")
    if current_tilt is None:
        return None
    if current_tilt != want:
        return ("miss", f"flipped to {current_tilt}")
    by, today = _to_date(pred.get("resolve_by")), _to_date(as_of)
    if by and today and today >= by:
        return ("hit", f"stayed {current_tilt}-tilted through resolve-by")
    return None                                   # still want, but the quarter isn't up


def resolve_deal_flow(pred, deals_since_made: int) -> tuple | None:
    thr = (pred.get("params") or {}).get("threshold", 2)
    if deals_since_made >= thr:
        return ("hit", f"{deals_since_made} ≥ {thr} material deals")
    return None


def resolve_reactivity(pred, sector_move_pcts) -> tuple | None:
    """sector_move_pcts: measured |moves| (%) for the sector's material deals since
    made_on. Hit as soon as one clears the threshold."""
    thr = (pred.get("params") or {}).get("threshold_pct", 2.0)
    if any(abs(p) >= thr for p in (sector_move_pcts or [])):
        return ("hit", f"a deal moved the stock ≥{thr:.0f}%")
    return None


def _close_on_or_before(series, d):
    """Last close on/before date d from an ascending [{date, close}] series."""
    val = None
    for p in series:
        pd_ = _to_date(p.get("date"))
        if pd_ and pd_ <= d:
            val = p.get("close")
        elif pd_ and pd_ > d:
            break
    return val


def resolve_price_move(pred, series) -> tuple | None:
    """Point-to-point: close at made_on → close at resolve_by. Only decides once we
    actually have price data through resolve_by (else leave open)."""
    if not series:
        return None
    made, by = _to_date(pred.get("made_on")), _to_date(pred.get("resolve_by"))
    dates = [_to_date(p.get("date")) for p in series if _to_date(p.get("date"))]
    if not dates or max(dates) < by:
        return None                              # window hasn't elapsed in our data yet
    base = _close_on_or_before(series, made)
    end = _close_on_or_before(series, by)
    if not base or not end or base <= 0:
        return None
    ret = (end - base) / base * 100
    p = pred.get("params") or {}
    thr, direction = p.get("threshold", 5.0), p.get("direction")
    hit = (direction == "up" and ret >= thr) or (direction == "down" and ret <= -thr)
    return ("hit" if hit else "miss", f"{ret:+.1f}% point-to-point")


def resolution_evidence(pred: dict, *, history=None, tilt=None, deals=None,
                        moves=None, series=None) -> dict:
    """Pure snapshot of what a resolver actually saw, persisted with the verdict so a
    resolution is REPRODUCIBLE after the source feed rows prune (14–30d). Built from the
    same inputs the resolve_* functions consume — stage_advance and price_move read
    never-pruned tables (technology_stage_history / stock_prices); deal_flow / reactivity
    count over the feed window, so snapshotting what they saw is how their verdict stays
    auditable once those rows age out."""
    kind = pred.get("kind")
    ev: dict = {"kind": kind, "subject": pred.get("subject")}
    if kind == "stage_advance":
        ev["stages_seen"] = [h.get("adoption_stage") for h in (history or [])
                             if h.get("technology") == pred.get("subject")]
    elif kind == "stage_advance_tech":
        # dated maturity display stages + contested flags — enough to re-derive the
        # confirmed-advance verdict (run ≥ 2 clean snapshots) after the fact.
        ev["snapshots_seen"] = [
            {"as_of": h.get("as_of"), "stage": h.get("maturity_stage"),
             "mixed": bool(h.get("maturity_mixed"))}
            for h in (history or []) if h.get("technology") == pred.get("subject")]
    elif kind == "radar_detection":
        ev["snapshots_seen"] = [
            {"as_of": h.get("as_of"), "stage": h.get("maturity_stage"),
             "articles": h.get("article_count")}
            for h in (history or []) if h.get("technology") == pred.get("subject")]
    elif kind == "posture_persist":
        ev["tilt_now"] = tilt
    elif kind == "deal_flow":
        ev["deals_since"] = deals
    elif kind == "reactivity":
        ev["moves_pct"] = list(moves or [])
    elif kind == "price_move":
        s = series or []
        ev["closes_seen"] = len(s)
        ev["last_close"] = s[-1].get("close") if s else None
    return ev


def is_overdue(pred, as_of) -> bool:
    by = _to_date(pred.get("resolve_by"))
    today = _to_date(as_of)
    return bool(by and today and today > by)


def manual_resolution_error(pred, outcome) -> str | None:
    """Why a forecast may NOT be human-graded — None if grading is allowed.

    The only human-gradable forecasts are still-open Strategist judgment calls
    (kind == 'manual'): every auto kind is graded objectively by the resolver
    job, and a resolved outcome is locked — the record is never regraded.
    Pure; every manual-resolution write path (API, UI) must consult this."""
    if outcome not in ("hit", "miss", "partial"):
        return "outcome must be hit | miss | partial"
    if not pred:
        return "forecast not found"
    if (pred.get("status") or "") != "open":
        return "already resolved — outcomes are locked once graded"
    if (pred.get("kind") or "") != "manual":
        return (f"'{pred.get('kind')}' forecasts are auto-graded against the data — "
                "only Strategist (judgment) calls can be graded manually")
    return None


# A forecast must test the FUTURE, not the made-day state: event-window kinds
# (deal_flow / reactivity / stage_advance) can't resolve to a HIT until at least this
# many days have elapsed since made_on (persistence + price kinds wait for resolve_by).
MIN_RESOLVE_DAYS = 7


def elapsed_days(pred, as_of) -> int:
    """Whole days between a forecast's made_on and `as_of` (0 if either is unparseable)."""
    made, today = _to_date(pred.get("made_on")), _to_date(as_of)
    return (today - made).days if made and today else 0


# ── scoring (pure) ──────────────────────────────────────────────────────────────
def accuracy(resolved) -> float | None:
    scored = [_OUTCOME_VALUE[p["outcome"]] for p in resolved
              if p.get("outcome") in _OUTCOME_VALUE]
    return round(sum(scored) / len(scored), 3) if scored else None


def _brier_pairs(resolved) -> list[tuple]:
    return [(p["confidence"], _OUTCOME_VALUE[p["outcome"]]) for p in resolved
            if p.get("confidence") is not None and p.get("outcome") in _OUTCOME_VALUE]


def brier_score(resolved) -> float | None:
    """Mean squared error between stated confidence and outcome (hit=1, partial=.5,
    miss=0). Lower is better; 0 is perfect, 0.25 is a coin flip at 50%."""
    pairs = _brier_pairs(resolved)
    if not pairs:
        return None
    return round(sum((c - o) ** 2 for c, o in pairs) / len(pairs), 3)


def naive_baseline(resolved) -> dict:
    """Does the record beat a dumb rule? Computed over the SAME resolved population
    as the accuracy/Brier it sits next to (so it inherits the quarantine when called
    from `track_record`). Pure.

      base_rate         — observed hit share among resolved (hit=1, partial=.5, miss=0)
      baseline_accuracy — 'always predict the majority outcome' → max(p, 1−p)
      baseline_brier    — 'always forecast the base-rate probability' (climatology)
                          → p·(1−p)
      brier_skill       — 1 − brier / baseline_brier. None when baseline_brier == 0:
                          the outcome never varies (e.g. an all-hit category), so no
                          discrimination has been tested yet — that itself is the tell.
      accuracy_edge_pp  — accuracy − baseline_accuracy, in percentage points.

    None means 'not computable', never 0."""
    outcomes = [_OUTCOME_VALUE[p["outcome"]] for p in resolved
                if p.get("outcome") in _OUTCOME_VALUE]
    if not outcomes:
        return {"base_rate": None, "baseline_accuracy": None, "baseline_brier": None,
                "brier_skill": None, "accuracy_edge_pp": None}
    base = sum(outcomes) / len(outcomes)          # == accuracy, unrounded
    baseline_acc = max(base, 1.0 - base)
    baseline_brier = base * (1.0 - base)
    pairs = _brier_pairs(resolved)
    brier = sum((c - o) ** 2 for c, o in pairs) / len(pairs) if pairs else None
    skill = (None if brier is None or baseline_brier == 0
             else 1.0 - brier / baseline_brier)
    return {
        "base_rate": round(base, 3),
        "baseline_accuracy": round(baseline_acc, 3),
        "baseline_brier": round(baseline_brier, 3),
        "brier_skill": round(skill, 3) if skill is not None else None,
        "accuracy_edge_pp": round((base - baseline_acc) * 100, 1),
    }


def calibration_bins(resolved, n_bins: int = 5) -> list[dict]:
    """Bucket resolved forecasts by stated confidence; report actual hit-rate per
    band. Perfect calibration → predicted ≈ actual."""
    buckets: dict = {}
    for p in resolved:
        o = _OUTCOME_VALUE.get(p.get("outcome"))
        c = p.get("confidence")
        if o is None or c is None:
            continue
        b = min(int(float(c) * n_bins), n_bins - 1)
        buckets.setdefault(b, []).append(o)
    out = []
    for b in sorted(buckets):
        vals = buckets[b]
        lo, hi = b / n_bins, (b + 1) / n_bins
        out.append({"band": f"{int(lo * 100)}–{int(hi * 100)}%",
                    "predicted": round((lo + hi) / 2, 3),
                    "actual": round(sum(vals) / len(vals), 3), "n": len(vals)})
    return out


# Quarantined kinds are logged and scored in their own category breakout, but
# EXCLUDED from the pooled headline stats (resolved counts / accuracy / Brier) —
# price-direction calls are deliberate coin flips (pinned 0.50), so pooling them
# would mechanically drag the headline toward 50% / 0.25 with zero skill change.
QUARANTINED_KINDS = ("price_move",)


def is_quarantined(pred) -> bool:
    return pred.get("kind") in QUARANTINED_KINDS


def track_record(predictions, *, include_quarantined: bool = False) -> dict:
    """Pooled scorecard. By default the quarantined kinds are excluded from the
    scored fields (resolved/hits/misses/accuracy/brier) so every headline consumer
    inherits the quarantine; `track_record_by_category` opts back in per group so
    price calls still get their own honest row. `quarantined_resolved` keeps the
    ledger reconcilable: resolved + quarantined_resolved == all resolved."""
    resolved_all = [p for p in predictions if p.get("status") == "resolved"]
    open_ = [p for p in predictions if p.get("status") != "resolved"]
    resolved = (resolved_all if include_quarantined
                else [p for p in resolved_all if not is_quarantined(p)])
    return {
        "total": len(predictions),
        "open": len(open_),
        "resolved": len(resolved),
        "quarantined_resolved": len(resolved_all) - len(resolved),
        "hits": sum(1 for p in resolved if p.get("outcome") == "hit"),
        "misses": sum(1 for p in resolved if p.get("outcome") == "miss"),
        "partials": sum(1 for p in resolved if p.get("outcome") == "partial"),
        "accuracy": accuracy(resolved),
        "brier": brier_score(resolved),
        # Naive-baseline comparison over the same (quarantine-respecting) population —
        # additive keys, so every existing consumer keeps working unchanged.
        **naive_baseline(resolved),
    }


_CATEGORY = {
    "stage_advance": "Technology",
    "stage_advance_tech": "Technology",
    "posture_persist": "Market structure",
    "deal_flow": "Market structure",
    "reactivity": "Market reactivity",
    "price_move": "Price (low-signal)",
    "manual": "Strategist (judgment)",
    "radar_detection": "Radar detection",
}


def category_of(kind: str) -> str:
    return _CATEGORY.get(kind, "Other")


# ── resolution basis: what a forecast is graded AGAINST (launch review 2.2) ───
# "external"    — a claim about the world (Strategist calls: mandates, approvals,
#                 launches, standards), graded by hand against public facts. The
#                 only basis a skeptical outsider can independently verify — so
#                 the only one allowed to headline.
# "internal"    — a claim about Lodestar's own future labels (stage transitions,
#                 posture persistence, deal-flow continuation). Partially
#                 self-referential: it measures the system's *consistency*, not
#                 its ability to predict the world. Scored openly, never hidden,
#                 but demoted from the headline and labeled as such.
# "quarantined" — price direction, treated as ~unforecastable (existing policy).
_BASIS = {
    "manual": "external",
    "stage_advance": "internal",
    "stage_advance_tech": "internal",
    "posture_persist": "internal",
    "deal_flow": "internal",
    "reactivity": "internal",
    "price_move": "quarantined",
    # graded against Lodestar's own placement pipeline (the evidence floor), so
    # it measures detection durability, not world events — internal by design
    "radar_detection": "internal",
}


def resolution_basis(kind: str) -> str:
    """What this forecast kind is graded against. Unknown kinds default to
    "internal" — the conservative bucket (never lets a new kind headline by
    accident). Pure."""
    return _BASIS.get(kind, "internal")


def records_by_basis(predictions) -> dict:
    """The external (world-graded, citable) and internal (self-referential,
    consistency-only) track records, each a full `track_record` dict. Pure.

    external + internal + quarantined_resolved reconcile to the full ledger —
    nothing is hidden, only re-headlined."""
    ext = [p for p in predictions if resolution_basis(p.get("kind")) == "external"]
    internal = [p for p in predictions if resolution_basis(p.get("kind")) == "internal"]
    return {
        "external": track_record(ext, include_quarantined=True),
        "internal": track_record(internal),
    }


def track_record_by_category(predictions) -> list[dict]:
    """Track record split by forecast category — this is where the quarantined price
    calls get scored (they're excluded from the pooled headline, never hidden).
    Each row carries its `basis` (external/internal/quarantined — every kind in a
    category shares one) so consumers can label what the score is graded against.
    Sorted by resolved desc."""
    groups: dict = {}
    for p in predictions:
        groups.setdefault(category_of(p.get("kind")), []).append(p)
    out = []
    for cat, preds in groups.items():
        tr = track_record(preds, include_quarantined=True)
        tr["category"] = cat
        tr["basis"] = resolution_basis(preds[0].get("kind"))
        out.append(tr)
    out.sort(key=lambda t: (-t["resolved"], -t["total"]))
    return out


def open_forecast_table(open_preds) -> list[dict]:
    """Compact, sortable rows for the open-forecasts table — one row per forecast,
    confidence desc. Collapses the verbose per-card text (basis/metadata) into
    columns so 60+ open calls stay scannable. Pure — Home renders via st.dataframe."""
    rows = []
    for p in sorted(open_preds, key=lambda x: -(x.get("confidence") or 0)):
        rows.append({
            "Category": category_of(p.get("kind")),
            "Forecast": p.get("claim") or "",
            "Conf %": int(round((p.get("confidence") or 0) * 100)),
            "Horizon": p.get("horizon") or "—",
            "Resolve by": p.get("resolve_by") or "—",
            "Type": "judgment" if p.get("kind") == "manual" else "auto",
        })
    return rows


def calibration_verdict(tr: dict) -> str:
    """Plain-English read of the Brier score (only meaningful with enough resolved)."""
    b = tr.get("brier")
    if b is None or tr.get("resolved", 0) < 4:
        return "calibration still building"
    if b <= 0.18:
        return "well-calibrated"
    if b <= 0.27:
        return "roughly calibrated"
    return "over-confident — claims are outrunning hits"


# A single headline accuracy % is too swingy below this many resolved (at N=4 one flip
# moves it 25pp), so every surface withholds the % until here — the ✓/✗ tally and the
# Brier-based calibration verdict (less swingy, available at ≥4) carry the record below it.
HEADLINE_ACCURACY_FLOOR = 10


def forecast_summary(predictions, tr: dict) -> str:
    """Executive forward-view line for the top of the tab."""
    open_preds = [p for p in predictions if p.get("status") != "resolved"]
    hi = sum(1 for p in open_preds if (p.get("confidence") or 0) >= 0.7)
    s = f"**Forward view:** {tr['open']} open forecast{'s' if tr['open'] != 1 else ''}"
    if hi:
        s += f" ({hi} high-conviction)"
    if tr["resolved"] >= HEADLINE_ACCURACY_FLOOR and tr["accuracy"] is not None:
        s += (f". Track record: **{tr['accuracy'] * 100:.0f}%** across {tr['resolved']} resolved "
              f"(Brier {tr['brier']:.2f} — {calibration_verdict(tr)}).")
    elif tr["resolved"]:
        s += (f". {tr['resolved']} resolved so far ({tr['hits']}✓ / {tr['misses']}✗) — "
              "record still building.")
    else:
        s += ". Nothing resolved yet — the track record starts now."
    return s


# ── the learning loop (pure) ─────────────────────────────────────────────────
# Resolved outcomes feed back to recalibrate each generator's stated confidence on
# *new* forecasts. Applied at generation time only — the fingerprint is independent
# of confidence, so this never edits a locked forecast (per the One Bet). Price calls
# stay pinned (the un-recalibrated 50% baseline) and Strategist calls carry their own
# conviction, so neither is recalibrated.
_RECALIBRATABLE = ("stage_advance", "stage_advance_tech", "posture_persist",
                   "deal_flow", "reactivity")


def realized_rates(predictions) -> dict:
    """Per-kind realized outcome rate (hit=1, partial=.5, miss=0) over resolved
    forecasts, with sample size — the empirical track record each generator is
    recalibrated against. Pure."""
    from collections import defaultdict
    agg: dict = defaultdict(list)
    for p in predictions:
        if p.get("status") != "resolved":
            continue
        o = _OUTCOME_VALUE.get(p.get("outcome"))
        if o is None:
            continue
        agg[p.get("kind")].append(o)
    return {k: {"rate": round(sum(v) / len(v), 3), "n": len(v)} for k, v in agg.items()}


def recalibrated_confidence(base, kind, rates, prior_strength: int = 6,
                            max_shift: float = 0.2) -> float:
    """Shrink a generator's heuristic `base` confidence toward its kind's realized
    hit-rate, weighted by sample size (a pseudo-count `prior_strength` so a thin
    record barely moves the prior). Bounded to ±`max_shift` and [0.05, 0.95] so one
    streak can't blow up a forecast's stated confidence. Pure.

        blended = (base·prior_strength + rate·n) / (prior_strength + n)
    """
    base = float(base)
    r = (rates or {}).get(kind)
    if not r or not r.get("n"):
        return round(base, 2)
    n, rate = r["n"], r["rate"]
    blended = (base * prior_strength + rate * n) / (prior_strength + n)
    blended = max(base - max_shift, min(base + max_shift, blended))
    return round(max(0.05, min(0.95, blended)), 2)


def apply_calibration(candidates, rates) -> list[dict]:
    """Recalibrate the auto quant kinds' stated confidence toward their realized
    track record (shrinkage-blended, bounded); leave `price_move` (pinned baseline)
    and `manual` (Strategist conviction) untouched. Annotates `basis` when it moves
    so the loop is visible per forecast. Returns new dicts — never mutates. Pure."""
    out = []
    for c in candidates:
        kind = c.get("kind")
        base = float(c.get("confidence") or 0.0)
        if kind not in _RECALIBRATABLE:
            out.append(c)
            continue
        adj = recalibrated_confidence(base, kind, rates)
        c2 = dict(c)
        if abs(adj - base) >= 0.01:
            r = rates.get(kind, {})
            c2["confidence"] = adj
            # Show the move and the sample, but NOT the raw realized rate — the ±cap
            # means adj rarely equals the rate, and printing both reads like an error.
            c2["basis"] = (c.get("basis") or "") + (
                f" · recalibrated {int(round(base * 100))}→{int(round(adj * 100))}% "
                f"from this kind's track record ({r.get('n', 0)} resolved)")
        out.append(c2)
    return out


def calibration_headline(predictions) -> dict:
    """Briefing-level credibility hero — the public, falsifiable track record as the
    *lead* proof point (not buried in the Forecasts tab). Overall accuracy + Brier
    across resolved forecasts (quarantined price calls excluded — see track_record),
    the plain-English calibration verdict, and the per-category cut (where the
    quarantined low-signal price calls stay visible with their own honest stats).
    A `state` gates how much the UI shows:

      empty    — nothing logged yet (brand promise only)
      seeded   — forecasts on the clock, none resolved (record building)
      building — resolved but not yet a scored verdict (1–3 resolved, or ≥4 that
                 still lack valid outcomes)
      live     — ≥4 resolved *with a real accuracy/Brier score* (full verdict)

    Pure: drives the Briefing banner; no network, no Streamlit, no clock."""
    tr = track_record(predictions)
    cats = [dict(c, verdict=calibration_verdict(c))
            for c in track_record_by_category(predictions) if c["resolved"]]
    if tr["resolved"] >= 4 and tr["accuracy"] is not None:
        state = "live"
    elif tr["resolved"] >= 1:
        state = "building"
    elif tr["total"] >= 1:
        state = "seeded"
    else:
        state = "empty"
    # The world-graded (external) cut rides along so no banner can quote the
    # pooled number as if it were world-prediction skill: until an external call
    # resolves, the pooled record is an internal-consistency measure and every
    # consumer can (and must) label it as such.
    ext = records_by_basis(predictions)["external"]
    external = {k: ext[k] for k in ("resolved", "open", "hits", "misses", "accuracy", "brier")}
    return {**tr, "state": state, "verdict": calibration_verdict(tr),
            "categories": cats, "external": external}


def calibration_tagline(headline: dict) -> str:
    """One-line credibility statement for the Briefing banner, keyed to record depth.

    Basis-aware: "89% accurate" must never read as world-prediction skill while the
    world-graded (external) record has zero resolutions — until then the pooled
    number is an internal-consistency measure and is labelled as such, with the
    world-graded status alongside. Once external calls resolve, they lead."""
    state = headline.get("state")
    if state == "empty":
        return ("Every call is locked the moment it's made and graded against our own data "
                "— no edits, no cherry-picking. The public track record starts with the first "
                "forecast.")
    if state == "seeded":
        n = headline["open"]
        return (f"{n} forecast{'s' if n != 1 else ''} on the clock, each locked when made and "
                "auto-graded against our own data. None have come due yet — the public record "
                "builds from here.")
    ext = headline.get("external") or {}
    ext_resolved = ext.get("resolved") or 0
    ext_open = ext.get("open") or 0
    if state == "building":
        r = headline["resolved"]
        world = (f" World-graded record: {ext_open} locked, none resolved yet."
                 if ext_resolved == 0 and ext_open else "")
        return (f"{r} forecast{'s' if r != 1 else ''} resolved so far "
                f"({headline['hits']}✓ / {headline['misses']}✗) — calibration sharpens into a "
                "verdict at ≥4 resolved. Every call locked when made." + world)
    # 'live' (≥4 resolved) shows the Brier verdict, but the swingy accuracy % is held
    # back until ≥HEADLINE_ACCURACY_FLOOR resolved — the ✓/✗ tally carries it until then.
    if ext_resolved > 0:
        lead = (f"World-graded: {ext['accuracy'] * 100:.0f}% accurate across {ext_resolved} resolved"
                if ext_resolved >= HEADLINE_ACCURACY_FLOOR and ext.get("accuracy") is not None
                else f"World-graded: {ext.get('hits', 0)}✓ / {ext.get('misses', 0)}✗ "
                     f"across {ext_resolved} resolved")
        if headline["resolved"] >= HEADLINE_ACCURACY_FLOOR:
            return (f"{lead} · internal consistency {headline['accuracy'] * 100:.0f}% "
                    f"over {headline['resolved']} resolved · Brier {headline['brier']:.2f} "
                    f"— {headline['verdict']}.")
        return f"{lead} · Brier {headline['brier']:.2f} — {headline['verdict']}."
    world = f" World-graded record: {ext_open} calls locked, none resolved yet." if ext_open else ""
    if headline["resolved"] >= HEADLINE_ACCURACY_FLOOR:
        return (f"Internal consistency: {headline['accuracy'] * 100:.0f}% accurate across "
                f"{headline['resolved']} resolved, locked-when-made self-graded calls · "
                f"Brier {headline['brier']:.2f} — {headline['verdict']}." + world)
    return (f"Internal consistency: {headline['resolved']} resolved "
            f"({headline['hits']}✓ / {headline['misses']}✗), locked-when-made · "
            f"Brier {headline['brier']:.2f} — {headline['verdict']}. "
            f"Headline accuracy holds at ≥{HEADLINE_ACCURACY_FLOOR} resolved." + world)


def calibration_chart(bins: list[dict]):
    """Predicted-vs-actual calibration scatter with the perfect-calibration
    diagonal. None when empty."""
    if not bins:
        return None
    df = pd.DataFrame(bins)
    diag = pd.DataFrame({"x": [0, 1], "y": [0, 1]})
    line = alt.Chart(diag).mark_line(strokeDash=[4, 4], color="#888").encode(
        x=alt.X("x:Q", title="Stated confidence",
                scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("y:Q", title="Actual hit-rate", scale=alt.Scale(domain=[0, 1])))
    pts = alt.Chart(df).mark_circle(opacity=0.85, color="#2f80c4").encode(
        x="predicted:Q", y="actual:Q",
        size=alt.Size("n:Q", title="Forecasts", scale=alt.Scale(range=[60, 700])),
        tooltip=[alt.Tooltip("band:N", title="Confidence band"),
                 alt.Tooltip("actual:Q", title="Hit-rate"),
                 alt.Tooltip("n:Q", title="n")])
    return (line + pts).properties(height=320)
