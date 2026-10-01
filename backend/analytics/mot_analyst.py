"""
MOT Analyst — turns the MOT-lens classifications on the stored articles into the
discipline's signature visual frameworks, each with a templated interpretation.

Pure reducers + Altair chart builders + a templated 7-questions scorecard. No
network, no Streamlit: reducers return plain structures, chart builders return
altair.Chart objects (validate headlessly with `.to_dict()`), interpretations
return short strings. The 🔭 tab in Home.py renders them; the agent-written
narrative is the Strategist (focus=<entity>).

Honest caveat: a true S-curve is performance vs. effort, which we don't measure —
so the S-curve here is a *lifecycle-positioning map*: the canonical curve as the
backdrop, with each maturity stage placed at its position and sized by volume.
"""

from __future__ import annotations

import math
from collections import Counter

import altair as alt
import pandas as pd

from analytics.entities import normalize as normalize_entity
from analytics.weights import article_weight, IMPACT_WEIGHTS

# ── ordered vocabularies (mirror the MOT Lens agent's allowed values) ─────────
MATURITY_ORDER = ["research", "emerging", "growth", "dominant-design", "mature", "declining"]
ADOPTION_ORDER = ["innovators", "early-adopters", "early-majority", "late-majority", "laggards"]
MOVE_ORDER = [
    "standards-battle", "entry-timing", "collaboration",
    "appropriability", "platform", "disruption",
]
# The decisive moves the doctrine says to surface (vs routine collaboration/timing).
DECISIVE_MOVES = {"standards-battle", "platform", "disruption", "appropriability"}


def _display_stage(p: dict, dim: str = "maturity") -> str | None:
    """The stage a placement is *displayed* at — delegates to the single source of
    truth, `tech_layer.display_stage` (committed stage, bare-modal fallback).
    Imported lazily so this module stays import-light (tech_layer pulls in the
    Supabase client stack at import time)."""
    from analytics.tech_layer import display_stage
    return display_stage(p, dim)


def scurve_position(p: dict) -> float | None:
    """Numeric S-curve position of a placement — the maturity centroid (where the dot
    actually sits), falling back to the displayed (committed/modal) stage's index.
    Rank/compare technologies with this so the ordering matches the chart, not the
    bare modal (which can flip the order on a bimodal spread). None when there's no
    usable maturity signal."""
    cen = p.get("stage_centroid")
    if isinstance(cen, (int, float)):
        return float(cen)
    stage = _display_stage(p)
    return float(MATURITY_ORDER.index(stage)) if stage in MATURITY_ORDER else None

_MATURITY_PALETTE = ["#6baed6", "#74c476", "#fd8d3c", "#e6550d", "#9e9ac8", "#969696"]
_ADOPTION_PALETTE = ["#9ecae1", "#6baed6", "#fd8d3c", "#74c476", "#969696"]

# x-position of each maturity stage along the canonical S-curve (0..1).
_MATURITY_X = {
    "research": 0.08, "emerging": 0.27, "growth": 0.5,
    "dominant-design": 0.72, "mature": 0.88, "declining": 0.97,
}
_STAGE_MEANING = {
    "research": "lab-stage, pre-commercial",
    "emerging": "early commercialization, no dominant design yet",
    "growth": "rapid adoption with a design converging",
    "dominant-design": "a standard has won; competition shifts to scale/cost",
    "mature": "saturated; incremental improvement",
    "declining": "being displaced by a newer technology",
}
# Representative z-positions for each adopter category on the diffusion bell.
_ADOPTION_Z = {
    "innovators": -2.2, "early-adopters": -1.3, "early-majority": -0.3,
    "late-majority": 0.7, "laggards": 1.8,
}
_CHASM_Z = -0.85          # the chasm sits between early-adopters and early-majority
_POST_CHASM = {"early-majority", "late-majority", "laggards"}


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-12.0 * (x - 0.5)))


def _normpdf(z: float) -> float:
    return math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)


def _val(row: dict, field: str) -> str:
    return (row.get(field) or "").strip().lower()


def _top_labels(items: list[dict], n: int = 3) -> str:
    """Top normalized companies (fallback to tags) across `items`, for tooltips."""
    c: Counter = Counter()
    for r in items:
        for comp in (r.get("companies") or []):
            nm = normalize_entity(str(comp))
            if nm:
                c[nm] += 1
    if not c:
        for r in items:
            for t in (r.get("tags") or []):
                if str(t).strip():
                    c[str(t).strip().lower()] += 1
    return ", ".join(name for name, _ in c.most_common(n)) or "—"


def _net_sentiment(items: list[dict]) -> int:
    pos = sum(1 for r in items if _val(r, "sentiment") == "positive")
    neg = sum(1 for r in items if _val(r, "sentiment") == "negative")
    return pos - neg


# ══════════════════════════════════════════════════════════════════════════════
# 1) S-curve lifecycle map
# ══════════════════════════════════════════════════════════════════════════════
def scurve_points(rows: list[dict]) -> list[dict]:
    by_stage: dict[str, list[dict]] = {}
    for r in rows:
        m = _val(r, "maturity_stage")
        if m in _MATURITY_X:
            by_stage.setdefault(m, []).append(r)
    pts = []
    for stage, items in by_stage.items():
        x = _MATURITY_X[stage]
        pts.append({
            "stage": stage,
            "x": x,
            "y": _logistic(x),
            "count": len(items),
            "top": _top_labels(items),
            "net_sentiment": _net_sentiment(items),
        })
    pts.sort(key=lambda p: p["x"])
    return pts


def scurve_chart(points: list[dict]):
    if not points:
        return None
    curve = pd.DataFrame({"x": [i / 60 for i in range(61)]})
    curve["y"] = curve["x"].map(_logistic)
    backdrop = alt.Chart(curve).mark_line(color="#cfcfcf", strokeWidth=2).encode(
        x=alt.X("x:Q", title="cumulative effort / time →",
                axis=alt.Axis(labels=False, ticks=False, grid=False)),
        y=alt.Y("y:Q", title="performance →",
                axis=alt.Axis(labels=False, ticks=False, grid=False)),
    )
    df = pd.DataFrame(points)
    df["label"] = df["stage"].str.replace("-", " ").str.title() + " (" + df["count"].astype(str) + ")"

    # Shaded lifecycle bands behind the curve (boundaries at the midpoints between
    # the fixed stage positions) — consistent with the technology S-curve.
    present = [p["stage"] for p in points]  # already x-sorted
    xs = [_MATURITY_X[s] for s in present]
    bounds = [0.0] + [(a + b) / 2 for a, b in zip(xs, xs[1:])] + [1.0]
    band_df = pd.DataFrame([
        {"x0": bounds[i], "x1": bounds[i + 1], "ylo": 0.0, "yhi": 1.0, "stage": present[i]}
        for i in range(len(present))
    ])
    bands = alt.Chart(band_df).mark_rect(opacity=0.12).encode(
        x="x0:Q", x2="x1:Q", y="ylo:Q", y2="yhi:Q",
        color=alt.Color("stage:N",
                        scale=alt.Scale(domain=MATURITY_ORDER,
                                        range=[_STAGE_TINT[s] for s in MATURITY_ORDER]),
                        legend=None),
    )
    dividers = alt.Chart(pd.DataFrame({"x": bounds[1:-1]})).mark_rule(
        color="#d0d5da", strokeDash=[4, 4]
    ).encode(x="x:Q")

    bubbles = alt.Chart(df).mark_circle(opacity=0.9, stroke="white", strokeWidth=1).encode(
        x="x:Q",
        y="y:Q",
        size=alt.Size("count:Q", scale=alt.Scale(range=[120, 1700]), legend=None),
        color=alt.Color("stage:N",
                        scale=alt.Scale(domain=MATURITY_ORDER, range=_MATURITY_PALETTE),
                        legend=None),
        tooltip=[alt.Tooltip("stage:N", title="Stage"),
                 alt.Tooltip("count:Q", title="Items"),
                 alt.Tooltip("top:N", title="Top players")],
    )
    labels = alt.Chart(df).mark_text(dy=-20, fontSize=11, fontWeight="bold").encode(
        x="x:Q", y="y:Q", text="label:N",
    )
    return (
        (bands + dividers + backdrop + bubbles + labels)
        .resolve_scale(color="independent")
        .properties(height=320)
    )


def interpret_scurve(points: list[dict]) -> str:
    if not points:
        return ""
    total = sum(p["count"] for p in points)
    dom = max(points, key=lambda p: p["count"])
    parts = [
        f"Most classified activity sits in **{dom['stage'].replace('-', ' ')}** "
        f"({dom['count']}/{total}) — {_STAGE_MEANING[dom['stage']]}."
    ]
    early = sum(p["count"] for p in points if p["stage"] in ("research", "emerging"))
    if early and early / total >= 0.20:
        parts.append(
            f"**Discontinuity watch:** {early} item(s) in *research/emerging* — "
            "a new S-curve may be starting (where incumbents get displaced)."
        )
    declining = next((p for p in points if p["stage"] == "declining"), None)
    if declining:
        parts.append(f"{declining['count']} *declining* — incumbents facing displacement.")
    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# 2) Diffusion & the chasm
# ══════════════════════════════════════════════════════════════════════════════
def diffusion_points(rows: list[dict]) -> list[dict]:
    by_stage: dict[str, list[dict]] = {}
    for r in rows:
        a = _val(r, "adoption_stage")
        if a in _ADOPTION_Z:
            by_stage.setdefault(a, []).append(r)
    pts = []
    for stage, items in by_stage.items():
        z = _ADOPTION_Z[stage]
        pts.append({
            "stage": stage,
            "z": z,
            "y": _normpdf(z),
            "count": len(items),
            "top": _top_labels(items),
            "crossed": stage in _POST_CHASM,
        })
    pts.sort(key=lambda p: p["z"])
    return pts


def diffusion_chart(points: list[dict]):
    if not points:
        return None
    bell = pd.DataFrame({"z": [(-30 + i) / 10 for i in range(61)]})  # -3..3
    bell["y"] = bell["z"].map(_normpdf)
    area = alt.Chart(bell).mark_area(color="#eef3f8", line={"color": "#cfcfcf"}).encode(
        x=alt.X("z:Q", title="adopter categories →",
                axis=alt.Axis(labels=False, ticks=False, grid=False)),
        y=alt.Y("y:Q", title="population", axis=alt.Axis(labels=False, ticks=False, grid=False)),
    )
    chasm = alt.Chart(pd.DataFrame({"z": [_CHASM_Z]})).mark_rule(
        color="#d62728", strokeDash=[5, 5]
    ).encode(x="z:Q")
    chasm_lbl = alt.Chart(pd.DataFrame({"z": [_CHASM_Z], "y": [0.42], "t": ["chasm"]})).mark_text(
        color="#d62728", dx=-16, fontSize=11, fontWeight="bold"
    ).encode(x="z:Q", y="y:Q", text="t:N")
    df = pd.DataFrame(points)
    df["label"] = df["stage"].str.replace("-", " ").str.title() + " (" + df["count"].astype(str) + ")"
    bubbles = alt.Chart(df).mark_circle(opacity=0.85).encode(
        x="z:Q", y="y:Q",
        size=alt.Size("count:Q", scale=alt.Scale(range=[120, 1500]), legend=None),
        color=alt.Color("stage:N",
                        scale=alt.Scale(domain=ADOPTION_ORDER, range=_ADOPTION_PALETTE),
                        legend=None),
        tooltip=[alt.Tooltip("stage:N", title="Adopter group"),
                 alt.Tooltip("count:Q", title="Items"),
                 alt.Tooltip("top:N", title="Top players")],
    )
    labels = alt.Chart(df).mark_text(dy=-18, fontSize=10).encode(x="z:Q", y="y:Q", text="label:N")
    return (area + chasm + chasm_lbl + bubbles + labels).properties(height=280)


# ── Confidence gating for templated modal verdicts (mirrors the S-curve fix) ──
# A verdict that rests on a modal/count is only asserted at face value when it has
# enough support: at least _MIN_SIGNAL_N classified items AND a clear plurality.
# Below that it is hedged ("thin / indicative") rather than stated as decisive.
_MIN_SIGNAL_N = 3
_MIN_PLURALITY = 0.5   # the modal must hold MORE than half; a thin/50-50 plurality is hedged


def _modal_confident(items: list[dict], field: str, order) -> tuple:
    """(modal, n, share) over the on-vocabulary values of `field`, or (None, 0, 0.0)
    if none. `n` = count with a usable value, `share` = the modal's fraction of it. Pure."""
    vals = [v for r in items if (v := _val(r, field)) in order]
    if not vals:
        return (None, 0, 0.0)
    modal, cnt = Counter(vals).most_common(1)[0]
    return (modal, len(vals), cnt / len(vals))


def _thin(n: int, share: float) -> bool:
    """A modal call is thin (hedge it) when under the count floor or lacking a majority."""
    return n < _MIN_SIGNAL_N or share <= _MIN_PLURALITY


def interpret_diffusion(points: list[dict]) -> str:
    if not points:
        return ""
    total = sum(p["count"] for p in points)
    crossed = sum(p["count"] for p in points if p["crossed"])
    if crossed:
        if crossed < _MIN_SIGNAL_N or total < _MIN_SIGNAL_N:
            # A chasm crossing is the most decisive market signal — so don't assert it
            # off a thin count; report it as indicative until the evidence is there.
            return (
                f"**{crossed}/{total}** item(s) have **crossed the chasm** into the early "
                "majority or beyond — but on a thin count; treat as *indicative*, not yet "
                "confirmed mainstream adoption."
            )
        return (
            f"**{crossed}/{total}** item(s) have **crossed the chasm** into the early "
            "majority or beyond — pragmatist (mainstream) adoption, the single most "
            "decisive market signal."
        )
    return (
        f"All **{total}** classified item(s) sit *pre-chasm* (innovators / early "
        "adopters) — visionary buzz, not yet mainstream pragmatist adoption."
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3) Strategic-move matrix (maturity × move)
# ══════════════════════════════════════════════════════════════════════════════
def move_matrix(rows: list[dict]) -> list[dict]:
    c: Counter = Counter()
    for r in rows:
        m = _val(r, "maturity_stage")
        mv = _val(r, "strategic_move")
        if m in _MATURITY_X and mv in MOVE_ORDER:
            c[(m, mv)] += 1
    return [{"maturity": m, "move": mv, "count": n} for (m, mv), n in c.items()]


def move_chart(cells: list[dict]):
    if not cells:
        return None
    df = pd.DataFrame(cells)
    base = alt.Chart(df).encode(
        x=alt.X("move:N", title=None, sort=MOVE_ORDER,
                axis=alt.Axis(labelAngle=-35)),
        y=alt.Y("maturity:N", title=None, sort=MATURITY_ORDER),
    )
    heat = base.mark_rect().encode(
        color=alt.Color("count:Q", scale=alt.Scale(scheme="blues"), legend=None),
        tooltip=[alt.Tooltip("maturity:N"), alt.Tooltip("move:N"), alt.Tooltip("count:Q")],
    )
    text = base.mark_text(fontSize=11).encode(
        text="count:Q",
        color=alt.condition("datum.count > 0", alt.value("#333"), alt.value("transparent")),
    )
    return (heat + text).properties(height=240)


def interpret_move(cells: list[dict]) -> str:
    if not cells:
        return ""
    total = sum(c["count"] for c in cells)
    if total < _MIN_SIGNAL_N:
        return f"Only **{total}** classified strategic move(s) — too few to read the move mix."
    top = max(cells, key=lambda c: c["count"])
    top_thin = top["count"] < _MIN_SIGNAL_N
    parts = [
        f"Most common play: **{top['move'].replace('-', ' ')}** in "
        f"**{top['maturity'].replace('-', ' ')}** ({top['count']})"
        + (" — thin, indicative." if top_thin else ".")
    ]
    decisive = sum(c["count"] for c in cells if c["move"] in DECISIVE_MOVES)
    if decisive:
        # Report the decisive *count* honestly, but only call it "winner-take-most
        # territory" when there's a concentrated leading play — not a scatter of
        # singletons that merely sum to the floor (which the top-cell hedge contradicts).
        verdict = " — winner-take-most territory." if (not top_thin and decisive >= _MIN_SIGNAL_N) else "."
        parts.append(
            f"**{decisive}/{total}** are decisive moves (standards battles, platform, "
            f"appropriability, disruption){verdict}"
        )
    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# 4) Momentum quadrant (maturity × momentum, per feed) — cross-feed
# ══════════════════════════════════════════════════════════════════════════════
def quadrant_points(rows: list[dict], momentum: list[dict]) -> list[dict]:
    """One point per feed: modal maturity (x), momentum % (y), recent volume (size).

    `momentum` is TrendsAggregator.momentum() output: [{feed(label), recent, pct}].
    """
    modal: dict[str, str] = {}
    for label in {r.get("_feed_label") for r in rows if r.get("_feed_label")}:
        c: Counter = Counter()
        for r in rows:
            if r.get("_feed_label") == label and _val(r, "maturity_stage") in _MATURITY_X:
                c[_val(r, "maturity_stage")] += 1
        if c:
            modal[label] = c.most_common(1)[0][0]
    out = []
    for m in momentum:
        label = m.get("feed")
        if label in modal:
            out.append({
                "feed": label,
                "maturity": modal[label],
                "momentum": float(m.get("pct") or 0),
                "volume": int(m.get("recent") or 0),
            })
    return out


def quadrant_chart(points: list[dict]):
    """One row per feed (no overlap), x = momentum %, dot colour = modal lifecycle
    stage, size = recent volume; a dashed line marks flat (0%). Rows sorted by
    momentum so the accelerating feeds are on top."""
    if not points:
        return None
    df = pd.DataFrame(points)
    order = [p["feed"] for p in sorted(points, key=lambda p: p["momentum"], reverse=True)]
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
        color="#c4ccd4", strokeDash=[4, 4]
    ).encode(x="x:Q")
    dots = alt.Chart(df).mark_circle(opacity=0.88, stroke="white", strokeWidth=1).encode(
        x=alt.X("momentum:Q", title="momentum %  (recent vs prior coverage)"),
        y=alt.Y("feed:N", sort=order, title=None),
        size=alt.Size("volume:Q", scale=alt.Scale(range=[140, 700]), legend=None),
        color=alt.Color("maturity:N",
                        scale=alt.Scale(domain=MATURITY_ORDER, range=_MATURITY_PALETTE),
                        legend=alt.Legend(title="modal lifecycle stage", orient="bottom")),
        tooltip=[alt.Tooltip("feed:N"), alt.Tooltip("maturity:N", title="modal stage"),
                 alt.Tooltip("momentum:Q", format="+.0f", title="momentum %"),
                 alt.Tooltip("volume:Q", title="recent articles")],
    )
    return (zero + dots).properties(height=max(220, 36 * len(points)))


def interpret_quadrant(points: list[dict]) -> str:
    if not points:
        return ""
    hot = max(points, key=lambda p: p["momentum"])
    parts = [
        f"**{hot['feed']}** has the strongest momentum ({hot['momentum']:+.0f}%), "
        f"sitting in **{hot['maturity'].replace('-', ' ')}**."
    ]
    cooling = [p for p in points if p["momentum"] < 0 and p["maturity"] in ("mature", "declining")]
    if cooling:
        parts.append(
            "Cooling + late-lifecycle: "
            + ", ".join(p["feed"] for p in cooling)
            + " — consolidation territory."
        )
    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# 5) Cross-domain convergence (entity × feed) — cross-feed
# ══════════════════════════════════════════════════════════════════════════════
def convergence_cells(rows: list[dict], top: int = 12) -> list[dict]:
    # Each mention is significance/source-weighted (weights.article_weight) so the
    # ranking favours material, reputable cross-domain coverage. Spanning 2+ feeds
    # stays presence-based; the displayed cell count is rounded.
    by_entity: dict[str, Counter] = {}
    for r in rows:
        label = r.get("_feed_label")
        if not label:
            continue
        w = article_weight(r)
        for comp in (r.get("companies") or []):
            nm = normalize_entity(str(comp))
            if nm:
                by_entity.setdefault(nm, Counter())[label] += w
    # Keep only entities that span 2+ feeds (the convergence signal).
    cross = {e: feeds for e, feeds in by_entity.items() if len(feeds) >= 2}
    ranked = sorted(cross.items(), key=lambda kv: -sum(kv[1].values()))[:top]
    cells = []
    for entity, feeds in ranked:
        for feed, n in feeds.items():
            cells.append({"entity": entity, "feed": feed, "count": round(n)})
    return cells


def convergence_chart(cells: list[dict]):
    if not cells:
        return None
    df = pd.DataFrame(cells)
    order = (
        df.groupby("entity")["count"].sum().sort_values(ascending=False).index.tolist()
    )
    base = alt.Chart(df).encode(
        x=alt.X("feed:N", title=None, axis=alt.Axis(labelAngle=-35)),
        y=alt.Y("entity:N", title=None, sort=order),
    )
    heat = base.mark_rect().encode(
        color=alt.Color("count:Q", scale=alt.Scale(scheme="oranges"), legend=None),
        tooltip=[alt.Tooltip("entity:N"), alt.Tooltip("feed:N"), alt.Tooltip("count:Q")],
    )
    text = base.mark_text(fontSize=11).encode(
        text="count:Q",
        color=alt.condition("datum.count > 0", alt.value("#333"), alt.value("transparent")),
    )
    return (heat + text).properties(height=max(160, 26 * len(order)))


def interpret_convergence(cells: list[dict]) -> str:
    if not cells:
        return "No entity spans two or more feeds in this window — no cross-domain convergence yet."
    by_entity: dict[str, set] = {}
    for c in cells:
        by_entity.setdefault(c["entity"], set()).add(c["feed"])
    top_entity = max(by_entity.items(), key=lambda kv: len(kv[1]))
    feeds = ", ".join(sorted(top_entity[1]))
    return (
        f"**{top_entity[0]}** spans **{len(top_entity[1])} feeds** ({feeds}) — the "
        "strongest cross-domain signal; convergence here is where the multi-technology "
        "level of analysis earns its keep."
    )


# ══════════════════════════════════════════════════════════════════════════════
# 5b) Technology S-curve — place each TECHNOLOGY (not feed bucket) on the curve
# ══════════════════════════════════════════════════════════════════════════════
_SCURVE_K = 6.0  # logistic steepness for the technology S-curve

# Light per-stage tints for the lifecycle bands (cool → warm across the curve).
_STAGE_TINT = {
    "research": "#9aa7b4", "emerging": "#7fb6df", "growth": "#74cda0",
    "dominant-design": "#52c4ba", "mature": "#f2c46a", "declining": "#e58a6c",
}
# Adopter-category tints for the innovation-adoption curve (reuse the diffusion palette).
_ADOPTION_TINT = dict(zip(ADOPTION_ORDER, _ADOPTION_PALETTE))


def _logit(y: float, k: float = _SCURVE_K) -> float:
    """Inverse of logistic(x)=1/(1+e^-k(x-0.5)) — the x on the curve for height y."""
    y = min(0.999, max(0.001, y))
    return 0.5 - (1.0 / k) * math.log((1.0 / y) - 1.0)


def _lifecycle_curve(placements, *, order, tint, centroid_of, articles_of, committed_of,
                     dist_of, mixed_of, stage_title, extra_tooltips=(), chasm_after=None,
                     min_articles=3, fixed_axis=False):
    """Shared 'technologies on an S-curve' exhibit for one lifecycle dimension (maturity
    or adoption). Each tech is placed by the **centroid** of its stage spread (so a
    contested tech sits at the *centre* of its spread, not on a thin plurality), ordered
    by that centroid and spaced at EVEN heights so right-side labels step up the curve
    and never collide. No-majority techs are FADED; those under `min_articles` on-curve
    articles are dropped. Optionally marks `chasm_after` with a distinct chasm divider.
    Dimension-agnostic — accessors are injected. Pure.

    `fixed_axis` (the diffusion curve): place each tech at its true centroid on a fixed
    axis spanning ALL `order` categories, and draw every category as an equal-width band
    — so the whole Rogers model shows (incl. empty late-majority / laggards) and the
    chasm always sits at its real boundary. The pre-chasm pile-up becomes visible instead
    of being spread across a dynamically-stretched band. Default (maturity S-curve) keeps
    the rank-walk up a logistic backdrop and only bands the stages that have techs."""
    pts = [p for p in placements if centroid_of(p) is not None and articles_of(p) >= min_articles]
    if not pts:
        return None
    ordered = sorted(pts, key=lambda p: (centroid_of(p), -articles_of(p)))
    n = len(ordered)
    y_lo, y_hi = 0.05, 0.95          # wide range so the curve fills the left→right span
    rows = []
    for i, p in enumerate(ordered):
        y = (y_lo + y_hi) / 2 if n == 1 else y_lo + (y_hi - y_lo) * i / (n - 1)
        cen = centroid_of(p)
        idx = max(0, min(len(order) - 1, round(cen)))
        committed = committed_of(p) or order[idx]
        on_curve = articles_of(p)
        dist = dist_of(p) or {}
        spread = (" · ".join(f"{s.replace('-', ' ')} {round(100 * c / on_curve)}%"
                             for s, c in sorted(dist.items(), key=lambda kv: -kv[1])[:3])
                  if on_curve and dist else "—")
        mixed = mixed_of(p)
        rows.append({**p, "stage": committed.replace("-", " "), "band": committed,
                     "x": (cen if fixed_axis else _logit(y)), "y": y, "size_n": on_curve,
                     "alpha": 0.4 if mixed else 0.9, "spread": spread,
                     "confidence": "mixed — no majority stage" if mixed else "clear"})
    df = pd.DataFrame(rows)

    if fixed_axis:
        # Full category axis: band k spans [k-0.5, k+0.5]; +right margin for labels.
        XD = [-0.6, (len(order) - 1) + 1.4]
    else:
        XD = [-0.02, 1.12]              # tight right margin for the longest label
    YD = [0.0, 1.0]

    def _ax():  # consistent hidden axes on every layer (mixing styles blanks it)
        return alt.Axis(labels=False, ticks=False, grid=False, domain=False, title=None)

    def _x(field="x"):
        return alt.X(f"{field}:Q", scale=alt.Scale(domain=XD), axis=_ax())

    def _y(field="y"):
        return alt.Y(f"{field}:Q", scale=alt.Scale(domain=YD), axis=_ax())

    if fixed_axis:
        # Every Rogers category as a fixed equal-width band (incl. empty ones).
        present = list(order)
        band_df = pd.DataFrame([{
            "x0": k - 0.5, "x1": k + 0.5, "ylo": 0.0, "yhi": 1.0,
            "cx": float(k), "stage": s.replace("-", " "),
        } for k, s in enumerate(order)])
        divider_x = [k + 0.5 for k in range(len(order) - 1)]
    else:
        # Bands span the x-extent of each present stage's techs; boundaries at midpoints.
        present = [s for s in order if any(r["band"] == s for r in rows)]
        xr = {s: (min(r["x"] for r in rows if r["band"] == s),
                  max(r["x"] for r in rows if r["band"] == s)) for s in present}
        bounds = [min(0.0, xr[present[0]][0] - 0.04)]
        for a, b in zip(present, present[1:]):
            bounds.append((xr[a][1] + xr[b][0]) / 2)
        bounds.append(xr[present[-1]][1] + 0.05)
        band_df = pd.DataFrame([{
            "x0": bounds[i], "x1": bounds[i + 1], "ylo": 0.0, "yhi": 1.0,
            "cx": (bounds[i] + bounds[i + 1]) / 2, "stage": present[i].replace("-", " "),
        } for i in range(len(present))])
        divider_x = bounds[1:-1]
    tint_scale = alt.Scale(domain=[s.replace("-", " ") for s in present],
                           range=[tint[s] for s in present])

    bands = alt.Chart(band_df).mark_rect(opacity=0.15).encode(
        x=_x("x0"), x2="x1:Q", y=_y("ylo"), y2="yhi:Q",
        color=alt.Color("stage:N", scale=tint_scale, legend=None),
    )
    dividers = alt.Chart(pd.DataFrame({"x": divider_x})).mark_rule(
        color="#c4ccd4", strokeDash=[4, 4]
    ).encode(x=_x())
    stage_text = alt.Chart(band_df).mark_text(
        fontSize=13, fontWeight="bold", baseline="bottom", dy=-2
    ).encode(x=_x("cx"), y=_y("ylo"), text="stage:N",
             color=alt.Color("stage:N", scale=tint_scale, legend=None))

    layers = [bands, dividers, stage_text]
    if not fixed_axis:
        # Logistic S-curve backdrop (only meaningful on the rank-walk maturity axis).
        arc = pd.DataFrame({"x": [i / 80 for i in range(81)]})
        arc["y"] = arc["x"].map(lambda x: 1.0 / (1.0 + math.exp(-_SCURVE_K * (x - 0.5))))
        layers.append(alt.Chart(arc).mark_line(color="#aab2bb", strokeWidth=3).encode(x=_x(), y=_y()))

    dots = alt.Chart(df).mark_circle(stroke="white", strokeWidth=1).encode(
        x=_x(), y=_y(),
        size=alt.Size("size_n:Q", scale=alt.Scale(range=[120, 700]), legend=None),
        color=alt.Color("domain:N", legend=alt.Legend(title="domain", orient="bottom")),
        opacity=alt.Opacity("alpha:Q", scale=None, legend=None),
        tooltip=[alt.Tooltip("label:N", title="Technology"),
                 alt.Tooltip("stage:N", title=stage_title),
                 alt.Tooltip("spread:N", title="Spread"),
                 alt.Tooltip("confidence:N", title="Confidence"),
                 alt.Tooltip("size_n:Q", title="On-curve articles"),
                 *extra_tooltips,
                 alt.Tooltip("entrants:Q", title="distinct players")],
    )
    labels = alt.Chart(df).mark_text(align="left", dx=12, fontSize=11, color="#24292f").encode(
        x=_x(), y=_y(), text="label:N",
    )

    # Moore's chasm: a distinct divider + label at the early-adopters → early-majority
    # boundary. On the fixed axis it always shows; on the rank axis only if both sides
    # have techs.
    chasm_cx = None
    if chasm_after and chasm_after in order:
        if fixed_axis:
            chasm_cx = order.index(chasm_after) + 0.5
        elif chasm_after in present and present.index(chasm_after) + 1 < len(present):
            chasm_cx = bounds[present.index(chasm_after) + 1]
    if chasm_cx is not None:
        layers.append(alt.Chart(pd.DataFrame({"x": [chasm_cx]})).mark_rule(
            color="#cf6679", strokeWidth=2, strokeDash=[2, 2]).encode(x=_x()))
        layers.append(alt.Chart(pd.DataFrame({"x": [chasm_cx], "y": [0.5], "t": ["⚠ the chasm"]}))
                      .mark_text(color="#cf6679", fontWeight="bold", fontSize=12,
                                 angle=270, dy=-7).encode(x=_x(), y=_y(), text="t:N"))
    layers += [dots, labels]
    return (alt.layer(*layers).resolve_scale(color="independent")
            .properties(height=max(540, 36 * n)))


def tech_scurve_chart(placements: list[dict], min_articles: int = 3):
    """Technologies on the **maturity** S-curve (Technology Dynamics): placed by the
    centroid of their maturity-stage spread, faded when contested. Dot size = on-curve
    coverage, colour = domain. Falls back to the modal `maturity` for placements that
    predate the spread fields."""
    def cen(p):
        c = p.get("stage_centroid")
        if c is None and p.get("maturity") in MATURITY_ORDER:      # backward-compat
            return float(MATURITY_ORDER.index(p["maturity"]))
        return c

    def arts(p):
        n = p.get("stage_articles")
        return (p.get("articles") or 0) if n is None else n

    def dist(p):
        return p.get("stage_dist") or ({p["maturity"]: arts(p)} if p.get("maturity") else {})

    return _lifecycle_curve(
        placements, order=MATURITY_ORDER, tint=_STAGE_TINT,
        centroid_of=cen, articles_of=arts, committed_of=lambda p: p.get("committed_stage"),
        dist_of=dist, mixed_of=lambda p: bool(p.get("mixed")),
        stage_title="Maturity (spread centroid)",
        extra_tooltips=[alt.Tooltip("adoption:N"), alt.Tooltip("move:N")],
        min_articles=min_articles)


def adoption_curve_chart(placements: list[dict], min_articles: int = 3):
    """The market-uptake companion to the maturity S-curve: the same technologies on
    the **diffusion** curve (Rogers) — innovators → early adopters → early/late majority
    → laggards — placed by the centroid of their adoption-stage spread, with Moore's
    CHASM marked between early adopters and early majority. Same visual language as
    tech_scurve_chart. Pure."""
    return _lifecycle_curve(
        placements, order=ADOPTION_ORDER, tint=_ADOPTION_TINT,
        centroid_of=lambda p: p.get("adoption_centroid"),
        articles_of=lambda p: p.get("adoption_articles") or 0,
        committed_of=lambda p: p.get("adoption_committed"),
        dist_of=lambda p: p.get("adoption_dist"),
        mixed_of=lambda p: bool(p.get("adoption_mixed")),
        stage_title="Adopter category (spread centroid)",
        extra_tooltips=[alt.Tooltip("move:N")],
        chasm_after="early-adopters", min_articles=min_articles, fixed_axis=True)


def interpret_tech(placements: list[dict], min_articles: int = 3) -> str:
    if not placements:
        return ""
    _stage = _display_stage

    def _on_curve(p):
        n = p.get("stage_articles")
        return (p.get("articles") or 0) if n is None else n

    # Only the techs the chart actually places (same floor + stage key) — so the
    # narrative never names a technology that isn't on the curve.
    placed = [p for p in placements if _stage(p) and _on_curve(p) >= min_articles]
    if not placed:
        return ""
    parts = [f"{len(placed)} tracked technologies placed by their lifecycle-stage spread."]
    emerging = [p["label"] for p in placed if _stage(p) in ("research", "emerging")]
    growth = [p["label"] for p in placed if _stage(p) == "growth"]
    if emerging:
        parts.append(f"**Early curve:** {', '.join(emerging[:4])} — watch for a discontinuity.")
    if growth:
        parts.append(f"**Growth:** {', '.join(growth[:4])} — design converging, land-grab phase.")
    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# 5c) Measured performance curve (a real S-curve from seeded benchmark data)
# ══════════════════════════════════════════════════════════════════════════════
def benchmark_chart(spec: dict):
    """Plot a technology's measured performance series over time (the real
    S-curve). `spec` is an entry from benchmarks.BENCHMARKS."""
    series = (spec or {}).get("series") or []
    if len(series) < 2:
        return None
    df = pd.DataFrame(series, columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"])
    unit = spec.get("unit", "")
    line = alt.Chart(df).mark_line(point=True, color="#0969da", strokeWidth=2).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("value:Q", title=f"{spec.get('metric', 'value')} ({unit})",
                scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("date:T"), alt.Tooltip("value:Q", title=unit)],
    )
    return line.properties(height=260)


# ══════════════════════════════════════════════════════════════════════════════
# 5d) Design convergence — ferment (many players) → dominant design (few)
# ══════════════════════════════════════════════════════════════════════════════
def ferment_regime(placements: list[dict]) -> list[dict]:
    """Label each technology ferment / converging / converged (A2), from its
    lifecycle stage and the number of distinct players competing in it."""
    out = []
    for p in placements:
        m, n = p.get("maturity"), (p.get("entrants") or 0)
        if m in ("research", "emerging") or (m == "growth" and n >= 4):
            regime = "ferment"          # no dominant design; many approaches
        elif m in ("dominant-design", "mature", "declining"):
            regime = "converged"        # a standard has won; scale/cost game
        else:
            regime = "converging"
        out.append({**p, "regime": regime})
    return out


def ferment_chart(regimed: list[dict]):
    pts = [r for r in regimed if r.get("maturity") in _MATURITY_X]
    if not pts:
        return None
    df = pd.DataFrame(pts)
    return alt.Chart(df).mark_circle(opacity=0.82).encode(
        x=alt.X("entrants:Q", title="distinct players  (ferment →)",
                axis=alt.Axis(tickMinStep=1, format="d"),
                scale=alt.Scale(domainMin=0, nice=True)),
        y=alt.Y("maturity:N", sort=MATURITY_ORDER, title="lifecycle stage"),
        size=alt.Size("articles:Q", scale=alt.Scale(range=[80, 800]), legend=None),
        color=alt.Color(
            "regime:N",
            scale=alt.Scale(domain=["ferment", "converging", "converged"],
                            range=["#fd8d3c", "#6baed6", "#1a7f37"]),
            legend=alt.Legend(orient="bottom", title=None),
        ),
        tooltip=[alt.Tooltip("label:N", title="Technology"), alt.Tooltip("maturity:N"),
                 alt.Tooltip("entrants:Q", title="players"), alt.Tooltip("articles:Q"),
                 alt.Tooltip("regime:N")],
    ).properties(height=300)


def interpret_ferment(regimed: list[dict]) -> str:
    if not regimed:
        return ""
    ferment = [r["label"] for r in regimed if r["regime"] == "ferment"]
    converged = [r["label"] for r in regimed if r["regime"] == "converged"]
    parts = []
    if ferment:
        parts.append(
            f"**Ferment** (many approaches, no dominant design — standards risk): "
            f"{', '.join(ferment[:5])}."
        )
    if converged:
        parts.append(
            f"**Converged** (a design has won — scale/cost game): {', '.join(converged[:5])}."
        )
    return " ".join(parts) or "All tracked technologies are mid-transition."


# ══════════════════════════════════════════════════════════════════════════════
# 5e) Capital posture — real options vs full commitments (E2)
# ══════════════════════════════════════════════════════════════════════════════
_CAPITAL_TAGS = {"funding", "m&a", "deal", "capex", "investment", "acquisition", "ipo"}
_OPTION_CUES = (
    "seed", "series a", "series b", "series c", "pilot", "early-stage", "early stage",
    "minority", "grant", "prototype", "demonstrat", "partnership", "joint venture",
    " jv", "stake", "raises", "funding round", "venture",
)
_COMMIT_CUES = (
    "acquir", "buyout", "merger", "takeover", "scale-up", "scale up", "mass production",
    "gigafactory", "billion", "multi-year", "multiyear", "build-out", "buildout",
    "full-scale", "commits", "commitment",
)


def _is_capital_row(r: dict) -> bool:
    """A deal / funding story: scope='deal' or a capital tag (funding/m&a/capex/…)."""
    tags = {str(t).strip().lower() for t in (r.get("tags") or [])}
    return _val(r, "scope") == "deal" or bool(tags & _CAPITAL_TAGS)


def capital_moves(rows: list[dict]) -> list[dict]:
    """Capital-move stories (deals / funding) classified as real option vs full
    commitment via transparent keyword cues (E2). 'unclear' when no cue fires."""
    out = []
    for r in rows:
        if not _is_capital_row(r):
            continue
        text = " ".join([str(r.get("title") or ""), str(r.get("summary") or "")]).lower()
        commit = any(c in text for c in _COMMIT_CUES)
        option = any(c in text for c in _OPTION_CUES)
        # Only an UNAMBIGUOUS single-cue story is typed. A story tripping BOTH cue sets
        # (e.g. a "$2bn Series B") used to default to 'commitment', poisoning the deal
        # board / posture / C:O ratio; now it's 'unclear' (neither side wins). 'unclear'
        # is excluded from the board, so an ambiguous deal no longer skews the read.
        kind = ("commitment" if commit and not option else
                "option" if option and not commit else
                "unclear")
        out.append({"title": r.get("title"), "feed": r.get("_feed_label"),
                    "kind": kind, "url": r.get("url"), "companies": r.get("companies") or [],
                    "published_at": r.get("published_at")})
    return out


def capital_board(rows: list[dict]) -> dict:
    """Group capital moves into named columns for the deal board: the actual
    commitments (conviction bets) vs real options (hedged bets). 'unclear' moves
    are excluded from the board. Pure."""
    moves = capital_moves(rows)
    commitment = [m for m in moves if m["kind"] == "commitment"]
    option = [m for m in moves if m["kind"] == "option"]
    return {
        "commitment": commitment,
        "option": option,
        "counts": {"commitment": len(commitment), "option": len(option),
                   "unclear": sum(1 for m in moves if m["kind"] == "unclear")},
        "shown": len(commitment) + len(option),
    }


def interpret_capital(board: dict) -> str:
    """One-line read of the capital posture from the deal board."""
    c, o = board["counts"]["commitment"], board["counts"]["option"]
    if c + o == 0:
        return "No clearly-typed capital moves (deals / funding) in the window."
    if c > o * 1.5:
        tone = (f"**Commitment-heavy ({c} commitments vs {o} options)** — capital is committing, "
                "not hedging: late-cycle conviction (or over-extension).")
    elif o > c * 1.5:
        tone = (f"**Option-heavy ({o} options vs {c} commitments)** — capital is still hedging with "
                "small staged bets: early, uncertain field.")
    else:
        tone = f"**Balanced ({c} commitments vs {o} options)** — mixed conviction."
    return tone + " _E2: under uncertainty, staged options buy information before committing._"


# ── 5f) Posture vs lifecycle, concentration, market structure & regulation (D+E) ──
_EARLY_MATURITY = {"research", "emerging", "growth"}
_LATE_MATURITY = {"dominant-design", "mature", "declining"}
# Sort order for business_impact, derived from the weight table so it can never drift
# out of sync with the vocabulary again (material > contextual > none).
_IMPACT_RANK = {k: i for i, k in enumerate(sorted(IMPACT_WEIGHTS, key=IMPACT_WEIGHTS.get, reverse=True))}
_CONCENTRATION_CUES = (
    "acquir", "buyout", "merger", "takeover", "consolidat", "monopol",
    "antitrust", "market share", "roll-up", "rollup",
)


def capital_posture(rows: list[dict]) -> dict:
    """Capital posture (E2) read against the maturity of the field the deals sit in
    (A1). Option-heavy fits an early/uncertain field; commitment-heavy fits a mature
    one. The *mismatch* is the signal: big commitments into an emerging field flag
    over-extension; small options in a mature field flag timidity. Pure."""
    board = capital_board(rows)
    c, o = board["counts"]["commitment"], board["counts"]["option"]
    cap_rows = [r for r in rows if _is_capital_row(r)]
    maturity, mat_n, mat_share = _modal_confident(cap_rows, "maturity_stage", MATURITY_ORDER)
    typed = c + o
    stance = ("commitment" if c > o * 1.5 else
              "option" if o > c * 1.5 else "balanced")
    flag = "aligned"
    if typed == 0:
        flag = "none"
    elif typed < _MIN_SIGNAL_N or _thin(mat_n, mat_share):
        # Don't headline 'over-extension' / 'timid' off one or two classified deals, or a
        # modal maturity with no clear majority — the audit's "asserted off one deal" bug.
        flag = "low-confidence"
    elif stance == "commitment" and maturity in _EARLY_MATURITY:
        flag = "over-extension"
    elif stance == "option" and maturity in _LATE_MATURITY:
        flag = "timid"
    return {"commitment": c, "option": o, "stance": stance,
            "maturity": maturity, "flag": flag, "n": typed}


def capital_concentration(rows: list[dict], top: int = 6) -> dict:
    """Where capital is concentrating: deal / funding moves counted by domain (feed)
    and by named party (entity). Pure."""
    by_feed: Counter = Counter()
    by_entity: Counter = Counter()
    total = 0
    for r in rows:
        if not _is_capital_row(r):
            continue
        total += 1
        w = article_weight(r)  # a material capital move from a top source weighs more
        if r.get("_feed_label"):
            by_feed[r["_feed_label"]] += w
        for comp in (r.get("companies") or []):
            nm = normalize_entity(str(comp))
            if nm:
                by_entity[nm] += w
    return {
        "total": total,  # raw count of capital-move stories (not weighted)
        "by_feed": [{"feed": f, "count": round(n)} for f, n in by_feed.most_common(top)],
        "by_entity": [{"entity": e, "count": round(n)} for e, n in by_entity.most_common(top)],
    }


def concentration_chart(items: list[dict], field: str):
    """Horizontal bar of capital-move counts by `field` ('feed' or 'entity'). None
    when empty. Single-layer bar — safe to render headlessly."""
    if not items:
        return None
    df = pd.DataFrame(items)
    return (
        alt.Chart(df)
        .mark_bar(color="#2f80c4", cornerRadiusEnd=3)
        .encode(
            x=alt.X("count:Q", title="deal / funding moves",
                    axis=alt.Axis(tickMinStep=1, format="d")),
            y=alt.Y(f"{field}:N", sort="-x", title=None),
            tooltip=[alt.Tooltip(f"{field}:N", title=field.title()),
                     alt.Tooltip("count:Q", title="Moves")],
        )
        .properties(height=max(70, min(len(df) * 30 + 12, 240)))
    )


def market_structure(rows: list[dict], top: int = 8) -> dict:
    """D — market structure & regulation signal. Deal moves that *concentrate* a
    market (M&A / consolidation cues, D1) and regulatory / market-failure events
    (regulatory scope, D2). Material impact first. Pure."""
    concentrating: list[dict] = []
    regulatory: list[dict] = []
    for r in rows:
        scope = _val(r, "scope")
        item = {"title": r.get("title"), "feed": r.get("_feed_label"),
                "url": r.get("url"), "companies": r.get("companies") or [],
                "impact": _val(r, "business_impact")}
        if scope == "regulatory":
            regulatory.append(item)
        elif scope == "deal":
            text = " ".join([str(r.get("title") or ""), str(r.get("summary") or "")]).lower()
            if any(cue in text for cue in _CONCENTRATION_CUES):
                concentrating.append(item)
    concentrating.sort(key=lambda x: _IMPACT_RANK.get(x["impact"], 9))
    regulatory.sort(key=lambda x: _IMPACT_RANK.get(x["impact"], 9))
    return {
        "concentrating": concentrating[:top],
        "regulatory": regulatory[:top],
        "counts": {"concentrating": len(concentrating), "regulatory": len(regulatory)},
    }


def interpret_market_structure(ms: dict) -> str:
    """One-line read of the market-structure / regulation signal (D)."""
    nc = ms["counts"]["concentrating"]
    nr = ms["counts"]["regulatory"]
    if nc == 0 and nr == 0:
        return "No market-concentrating deals or regulatory events in the window."
    parts = []
    if nc:
        parts.append(
            f"**{nc} concentrating move(s)** — M&A / consolidation pushing toward fewer, "
            "larger players (D1: structure tightening)."
        )
    if nr:
        parts.append(
            f"**{nr} regulatory / market-failure event(s)** — the rules of the game are "
            "shifting (D2)."
        )
    return " ".join(parts) + " _D: market structure and regulation decide who can capture the rents._"


# ══════════════════════════════════════════════════════════════════════════════
# 6) 7-questions scorecard (templated) — the consultant deliverable backbone
# ══════════════════════════════════════════════════════════════════════════════
def entity_universe(rows: list[dict], top: int = 40) -> list[str]:
    # Ranked by significance/source-weighted mentions (weights.article_weight) so the
    # scorecard picker surfaces the entities in the most material, reputable coverage.
    c: Counter = Counter()
    for r in rows:
        w = article_weight(r)
        for comp in (r.get("companies") or []):
            nm = normalize_entity(str(comp))
            if nm:
                c[nm] += w
    return [name for name, _ in c.most_common(top)]


def _mentions(rows: list[dict], entity: str) -> list[dict]:
    out = []
    for r in rows:
        names = {normalize_entity(str(c)) for c in (r.get("companies") or [])}
        if entity in names:
            out.append(r)
    return out


def _modal(items: list[dict], field: str, allowed: list[str]) -> str | None:
    c = Counter(v for r in items if (v := _val(r, field)) in allowed)
    return c.most_common(1)[0][0] if c else None


def scorecard(rows: list[dict], entity: str) -> dict:
    """Templated answers to the doctrine's 7 questions for one entity, from the
    classified rows that mention it. Deterministic; the agent narrative is separate."""
    items = _mentions(rows, entity)
    n = len(items)
    feeds = sorted({r.get("_feed_label") for r in items if r.get("_feed_label")})
    maturity, mat_n, mat_share = _modal_confident(items, "maturity_stage", MATURITY_ORDER)
    adoption = _modal(items, "adoption_stage", ADOPTION_ORDER)
    move, move_n, move_share = _modal_confident(items, "strategic_move", MOVE_ORDER)
    impact = Counter(_val(r, "business_impact") for r in items if _val(r, "business_impact"))
    scope = Counter(_val(r, "scope") for r in items if _val(r, "scope"))
    crossed = any(_val(r, "adoption_stage") in _POST_CHASM for r in items)

    def q(question: str, answer: str) -> dict:
        return {"q": question, "a": answer}

    return {
        "entity": entity,
        "mentions": n,
        "feeds": feeds,
        "questions": [
            q("1. Lifecycle (S-curve)",
              ((f"Tentatively **{maturity.replace('-', ' ')}** (n={mat_n}, thin) — {_STAGE_MEANING[maturity]}."
                if _thin(mat_n, mat_share) else
                f"Mostly **{maturity.replace('-', ' ')}** — {_STAGE_MEANING[maturity]}.") if maturity
               else "Not enough classified items to place on the S-curve.")),
            q("2. Diffusion (chasm)",
              (f"Reaching **{adoption.replace('-', ' ')}**"
               + (" — has crossed the chasm into mainstream adoption." if crossed
                  else " — still pre-chasm (visionary/early-adopter).")) if adoption
              else "No adoption-stage signal."),
            q("3. Strategic move",
              ((f"Leading move (thin, n={move_n}): **{move.replace('-', ' ')}**."
                if _thin(move_n, move_share) else
                f"Predominant move: **{move.replace('-', ' ')}**"
                + (" — a decisive, winner-take-most play." if move in DECISIVE_MOVES else "."))
               if move else "No clear strategic move.")),
            q("4. Market & regulation",
              f"Impact mix: {dict(impact) or '—'}; scope: {dict(scope) or '—'}."),
            q("5. Capital",
              "Deal/funding activity present." if scope.get("deal") else
              "No explicit deal/funding scope in the window."),
            q("6. Decision quality (actors)",
              f"Appears across {len(feeds)} feed(s): {', '.join(feeds) or '—'}."),
            q("7. Confidence",
              f"Based on **{n}** classified mention(s)"
              + (" — thin; treat as indicative." if n < 3 else " — reasonable signal.")),
        ],
    }
