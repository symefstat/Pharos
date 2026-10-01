"""
Technology dossier — the exportable, citable one-pager per tracked technology.

Analysts live in documents: a dossier travels into a deck or a diligence pack
where a dashboard can't. This module assembles everything Lodestar knows about
one technology — current lifecycle placement (anchored, evidence-counted),
dated stage-transition history, the open forecasts on it WITH their falsifiers
("what would prove us wrong"), the resolved receipts, recent coverage, and the
measured world curve where one exists — into a single dict, then renders it as
clean Markdown or a PDF (mirroring analytics/strategist.py's fpdf2 approach).

Everything here is pure: `build_dossier` takes its inputs as arguments (the
backend route does the I/O — see backend/app/mot.py `/api/mot/dossier`), so the
builder and both renderers are unit-testable with fixtures and degrade
gracefully — a tech with no placement, no transitions or no forecasts still
yields a valid (smaller) dossier; an unknown tech yields None.
"""

from __future__ import annotations

from technologies import TECH_BY_KEY, Technology, domain_label
from analytics.tech_layer import (
    EVIDENCE_FLOOR,
    display_stage,
    match_technologies,
)

# How many recent matched stories the dossier quotes — enough to show the
# evidence base, few enough to stay a one-pager.
MAX_STORIES = 8

METHODOLOGY = (
    "Lifecycle placements derive from headline+summary news classification "
    "(MOT lens), rolled up per technology over a rolling 30-day window and "
    "floored by curated anchor stage assessments — news can advance a stage "
    "past its anchor, never lower it below. A technology with fewer than "
    f"{EVIDENCE_FLOOR} stage-classified articles in the window is reported as "
    "'watching — insufficient evidence' rather than placed on the curves. "
    "Forecasts are logged with locked terms and falsifiers, resolved against "
    "the public record, and graded in the open ledger. Full method: the "
    "/methodology page of the Lodestar app."
)


def _mentions(claim: str, label: str) -> bool:
    return bool(label) and label.lower() in (claim or "").lower()


def _truncate(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _stage_falsifier(p: dict, label: str) -> str:
    """Synthesised falsifier for an anchored stage-transition call: the claim
    is auto-resolved against the stage history, so 'wrong' has a precise shape."""
    params = p.get("params") or {}
    frm = params.get("from_stage") or "its current stage"
    to = params.get("to_stage") or "the next stage"
    by = p.get("resolve_by") or "the resolution date"
    return (f"{label} has not advanced from '{frm}' to '{to}' "
            f"(confirmed in the stage history) by {by}")


def _forecast_row(p: dict, label: str) -> dict:
    params = p.get("params") or {}
    if p.get("kind") == "manual":
        falsifier = str(params.get("falsifier") or "").strip() or None
    else:
        falsifier = _stage_falsifier(p, label)
    return {
        "kind": p.get("kind"),
        "claim": p.get("claim"),
        "confidence": p.get("confidence"),
        "horizon": p.get("horizon"),
        "made_on": p.get("made_on"),
        "resolve_by": p.get("resolve_by"),
        "falsifier": falsifier,
        # resolved-only fields (None while open)
        "outcome": p.get("outcome"),
        "resolved_on": p.get("resolved_on"),
        "evidence": p.get("resolution_note"),
    }


def _tech_forecasts(predictions: list[dict], tech_key: str, label: str) -> list[dict]:
    """The forecasts ABOUT this technology: anchored stage-transition calls by
    subject (same grouping backend/app/ledger.py tech_sections uses) plus
    judgment (`manual`) calls whose claim names the technology. Pure."""
    out = []
    for p in predictions or []:
        kind = p.get("kind")
        if kind == "stage_advance_tech" and p.get("subject") == tech_key:
            out.append(p)
        elif kind == "manual" and _mentions(p.get("claim") or "", label):
            out.append(p)
    out.sort(key=lambda p: str(p.get("made_on") or ""), reverse=True)
    return out


def _tech_stories(stories: list[dict], tech_key: str,
                  techs: list[Technology] | None = None) -> list[dict]:
    """Most recent stories matching the technology's registry keywords. Pure."""
    matched = [r for r in stories or [] if tech_key in match_technologies(r, techs)]
    matched.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)
    return [{
        "title": r.get("title"),
        "date": str(r.get("published_at") or "")[:10] or None,
        "source": r.get("source_name") or r.get("_feed_label"),
        "url": r.get("url"),
    } for r in matched[:MAX_STORIES]]


def _players(matched: list[dict], top: int = 8) -> list[dict]:
    """Most-named companies across this technology's matched stories, counted
    under their canonical entity name so surface-form variants ("IQM" vs "IQM
    Quantum Computers") never split one player into two. Pure."""
    from collections import Counter

    from analytics.entities import normalize

    counts: Counter = Counter()
    for r in matched:
        for c in r.get("companies") or []:
            name = normalize(str(c))
            if name:
                counts[name] += 1
    return [{"name": n, "mentions": c} for n, c in counts.most_common(top)]


def _analyst_read(label: str, placement: dict, p: dict, trans: list[dict],
                  open_fc: list[dict], resolved_fc: list[dict], capital: dict,
                  funding_section: dict | None, players: list[dict]) -> list[str]:
    """The composed verdict — a few plain-English paragraphs assembled from
    everything the dossier already knows, so every technology page opens with
    an actual analysis rather than a stack of sections. Deterministic and
    honest: each sentence names the evidence it rests on; sections with
    nothing to say are omitted rather than padded. Pure."""
    from analytics.mot_analyst import _POST_CHASM, _STAGE_MEANING

    out: list[str] = []

    # 1 — where it stands, and what that stage MEANS
    if placement["watching"]:
        out.append(
            f"**Where it stands.** {label} is on the watch list, not the curve: "
            f"{placement['evidence']} stage-classified article"
            f"{'s' if placement['evidence'] != 1 else ''} in the last 30 days is below "
            f"the evidence floor of {placement['evidence_floor']}, so Lodestar makes no "
            "stage claim yet. The sections below show what the thin coverage does say.")
    else:
        mat = placement["maturity"] or ""
        meaning = _STAGE_MEANING.get(mat, "")
        adoption = placement["adoption"] or ""
        chasm = ("past the chasm — mainstream, pragmatist buyers are adopting"
                 if adoption in _POST_CHASM else
                 "pre-chasm — adoption is still visionary, not mainstream")
        anchor = (" The placement is floored by a curated assessment"
                  + (f" ({placement['anchor_as_of']})" if placement["anchor_as_of"] else "")
                  + " — news can advance it, never lower it." if placement["anchored"] else "")
        out.append(
            f"**Where it stands.** {label} reads **{mat}** on the S-curve"
            + (f" — {meaning}" if meaning else "") +
            f" — on {placement['evidence']} stage-classified articles (30d). "
            f"Adoption reads **{adoption}**: {chasm}.{anchor}")

    # 2 — how the read changed
    fresh = [t for t in trans if not t.get("backward")]
    if fresh:
        latest = fresh[0]
        status = ("confirmed" if latest.get("confirmed")
                  else "pending a confirming snapshot")
        out.append(
            f"**How the read changed.** Most recent move: {latest['dimension']} "
            f"{latest['from']} → {latest['to']} ({latest['as_of']}, {status})"
            + (f"; {len(fresh) - 1} earlier move{'s' if len(fresh) > 2 else ''} on record."
               if len(fresh) > 1 else "."))

    # 3 — who's moving, and how capital is behaving
    move = (p.get("move") or "").replace("-", " ") if p else ""
    entrants = p.get("entrants") if p else None
    c, o = capital["counts"]["commitment"], capital["counts"]["option"]
    bits: list[str] = []
    if move:
        bits.append(f"the dominant strategic play in coverage is **{move}**")
    if entrants:
        bits.append(f"{entrants} distinct player{'s' if entrants != 1 else ''} named")
    if c + o > 0:
        posture = ("conviction-heavy — capital is committing, not hedging" if c > o * 1.5
                   else "option-heavy — capital is buying information, not committing"
                   if o > c * 1.5 else "split between conviction bets and hedges")
        bits.append(f"capital shows {c} commitment{'s' if c != 1 else ''} vs "
                    f"{o} option{'s' if o != 1 else ''} ({posture})")
    if top := players[:3]:
        bits.append("most-named: " + ", ".join(pl["name"] for pl in top))
    if bits:
        joined = "; ".join(bits)
        # upper-case only the first letter — .capitalize() would lowercase names
        out.append("**Who's moving.** " + joined[0].upper() + joined[1:] + ".")

    # 4 — the independent funding read, when it exists
    if funding_section and funding_section.get("read"):
        out.append(f"**Independent capital check.** {funding_section['read']}")

    # 5 — the record and the nearest test
    if resolved_fc:
        hits = sum(1 for f in resolved_fc if f.get("outcome") == "hit")
        misses = sum(1 for f in resolved_fc if f.get("outcome") == "miss")
        out.append(f"**Record on this technology.** {hits}✓ / {misses}✗ across "
                   f"{len(resolved_fc)} resolved call{'s' if len(resolved_fc) != 1 else ''} "
                   "— receipts below.")
    nearest = min((f for f in open_fc if f.get("resolve_by")),
                  key=lambda f: str(f["resolve_by"]), default=None)
    if nearest:
        wrong = f" Wrong if: {nearest['falsifier']}" if nearest.get("falsifier") else ""
        out.append(f"**The nearest test.** \"{_truncate(nearest.get('claim'), 160)}\" "
                   f"resolves by {nearest['resolve_by']}.{wrong}")
    return out


def _tech_capital(stories: list[dict], tech_key: str,
                  techs: list[Technology] | None = None) -> dict:
    """Capital moves (deals / funding) among this technology's matched stories,
    typed real-option vs commitment by the same cues the Capital board uses.
    Pure; degrades to zero counts when nothing matches."""
    from analytics.mot_analyst import capital_moves

    matched = [r for r in stories or [] if tech_key in match_technologies(r, techs)]
    moves = capital_moves(matched)
    moves.sort(key=lambda m: str(m.get("published_at") or ""), reverse=True)
    commitment = [m for m in moves if m["kind"] == "commitment"]
    option = [m for m in moves if m["kind"] == "option"]
    return {
        "commitment": commitment[:6],
        "option": option[:6],
        "counts": {"commitment": len(commitment), "option": len(option)},
    }


def build_dossier(tech_key: str, *, placements: list[dict], transitions: list[dict],
                  predictions: list[dict], stories: list[dict], measured: list[dict],
                  as_of: str, techs: list[Technology] | None = None,
                  funding: list[dict] | None = None) -> dict | None:
    """Assemble the dossier dict for one tracked technology (pure).

    Inputs are the standard read products: anchored placements
    (tech_layer.apply_anchors(placements(...))), detect_transitions() output,
    raw prediction rows, recent article rows, and measured_curves(). `techs`
    defaults to the static registry; pass the merged registry
    (technologies.registry(client)) so self-serve tracked technologies export
    too. Returns None for a key that isn't in the registry; every section
    degrades to empty/None when its input carries nothing for this tech.
    """
    by_key = {t.key: t for t in techs} if techs is not None else TECH_BY_KEY
    tech = by_key.get(tech_key)
    if tech is None:
        return None

    p = next((x for x in placements or [] if x.get("tech") == tech_key), {})
    evidence = p.get("stage_articles")
    if evidence is None:
        evidence = p.get("articles") or 0
    # No placement row at all = no coverage in the window = watching by definition.
    watching = bool(p.get("watching")) if p else True
    placement = {
        # Watching = insufficient evidence to place: the dossier makes NO stage
        # claim (the news-derived read stays visible in the app, not here).
        "maturity": None if watching else display_stage(p),
        "adoption": None if watching else display_stage(p, "adoption"),
        "watching": watching,
        "thin_signal": bool(p.get("thin_signal", not p)),
        "evidence": evidence,
        "evidence_floor": EVIDENCE_FLOOR,
        "anchored": bool(p.get("anchored")),
        "anchor_as_of": p.get("anchor_as_of"),
        "lifecycle_fit": p.get("lifecycle_fit", True) is not False,
        "lifecycle_note": p.get("lifecycle_note"),
    }

    trans = [{
        "dimension": t.get("dimension"),
        "from": t.get("from"),
        "to": t.get("to"),
        "as_of": t.get("as_of"),
        "contested": bool(t.get("contested")),
        "confirmed": bool(t.get("confirmed")),
        "backward": bool(t.get("backward")),
    } for t in transitions or [] if t.get("technology") == tech_key]
    trans.sort(key=lambda t: str(t.get("as_of") or ""), reverse=True)

    fc = _tech_forecasts(predictions, tech_key, tech.label)
    open_fc = [_forecast_row(x, tech.label) for x in fc if x.get("status") == "open"]
    resolved_fc = [_forecast_row(x, tech.label) for x in fc if x.get("status") == "resolved"]

    # Funding signal — the independent (non-news) evidence stream. None when the
    # table isn't set up or carries nothing for this tech; the dossier then
    # omits the panel entirely rather than showing a wall of zeros.
    funding_section = None
    if funding:
        from datetime import date

        from analytics.funding import funding_read, funding_summary

        today = date.fromisoformat(as_of)
        summary = funding_summary(funding, today)
        if summary:
            summary["read"] = funding_read(
                funding, None if watching else display_stage(p), today)
            funding_section = summary

    curve = next((c for c in measured or [] if c.get("tech_key") == tech_key), None)
    if curve:
        curve = {
            "label": curve.get("label"),
            "unit": curve.get("unit"),
            "series": [dict(pt) for pt in curve.get("series") or []],
            "source": dict(curve.get("source") or {}),
            "direction_note": curve.get("direction_note"),
        }

    capital = _tech_capital(stories, tech_key, techs)
    matched = [r for r in stories or [] if tech_key in match_technologies(r, techs)]
    players = _players(matched)
    return {
        "tech": tech_key,
        "label": tech.label,
        "domain": domain_label(tech.domain),
        "as_of": as_of,
        "placement": placement,
        # The composed verdict — the page/export opens with an actual analysis.
        "read": _analyst_read(tech.label, placement, p, trans, open_fc, resolved_fc,
                              capital, funding_section, players),
        "players": players,
        "transitions": trans,
        "open_forecasts": open_fc,
        "resolved_forecasts": resolved_fc,
        "stories": _tech_stories(stories, tech_key, techs),
        "capital": capital,
        "funding": funding_section,
        "measured_curve": curve,
        "methodology": METHODOLOGY,
    }


# ── Markdown renderer ──────────────────────────────────────────────────────────

def _pct(v) -> str:
    try:
        return f"{round(float(v) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _placement_lines(d: dict) -> list[str]:
    pl = d["placement"]
    lines = ["## Current placement", ""]
    if not pl["lifecycle_fit"]:
        note = pl.get("lifecycle_note") or "a single lifecycle label is a forced fit"
        lines.append(f"Not lifecycle-tracked: {note}")
        return lines
    if pl["watching"]:
        lines.append(
            f"**Watching — insufficient evidence.** {pl['evidence']} stage-classified "
            f"articles in the rolling window is below the {pl['evidence_floor']}-article "
            "evidence floor, so no stage is claimed; the technology stays tracked and "
            "re-enters the curves as coverage accrues."
        )
        return lines
    stage = lambda s: (s or "—").replace("-", " ")  # noqa: E731
    lines.append(f"- **Maturity (S-curve):** {stage(pl['maturity'])}")
    lines.append(f"- **Adoption (diffusion):** {stage(pl['adoption'])}")
    ev = f"- **Evidence:** {pl['evidence']} stage-classified articles (30-day window)"
    if pl["thin_signal"]:
        ev += " — thin signal, low-confidence placement"
    lines.append(ev)
    if pl["anchored"]:
        vintage = f" ({pl['anchor_as_of']})" if pl.get("anchor_as_of") else ""
        lines.append(f"- **Anchor:** curated stage assessment{vintage} floors this placement; "
                     "news can advance it, never lower it")
    return lines


def dossier_to_markdown(d: dict) -> str:
    """Render a dossier dict as clean, citable Markdown (pure)."""
    lines = [
        "# Lodestar — Technology Dossier",
        f"## {d['label']}" + (f" ({d['domain']})" if d.get("domain") else ""),
        f"_Generated {d['as_of']} · lodestar technology dossier_",
        "",
    ]
    lines += _placement_lines(d)
    lines.append("")

    # Agent narrative (when cached — added by the backend route) outranks the
    # deterministic paragraphs, matching what the page shows.
    agent = d.get("agent_read")
    if agent and agent.get("text"):
        lines += [f"## Analyst read _(agent-composed, {agent.get('as_of')})_", "",
                  agent["text"], ""]
    elif d.get("read"):
        lines += ["## Analyst read", ""]
        for para in d["read"]:
            lines += [para, ""]

    if d.get("players"):
        lines += ["## Key players (by mentions, 30d)", ""]
        lines.append(" · ".join(f"{pl['name']} ({pl['mentions']})" for pl in d["players"]))
        lines.append("")

    if d["transitions"]:
        lines += ["## Stage-transition history", ""]
        for t in d["transitions"]:
            flags = " · ".join(f for f in (
                "contested" if t["contested"] else "",
                "unconfirmed" if not t["confirmed"] else "",
                "backward (likely re-estimation noise)" if t["backward"] else "",
            ) if f)
            tail = f" ({flags})" if flags else ""
            lines.append(f"- {t['as_of'] or '—'} — {t['dimension']}: "
                         f"{t['from']} → {t['to']}{tail}")
        lines.append("")

    if d["open_forecasts"]:
        lines += ["## Open forecasts — what would prove us wrong", ""]
        for f in d["open_forecasts"]:
            meta = " · ".join(x for x in (
                f"confidence {_pct(f['confidence'])}" if f.get("confidence") is not None else "",
                f"made {f['made_on']}" if f.get("made_on") else "",
                f"resolves by {f['resolve_by']}" if f.get("resolve_by") else "",
            ) if x)
            lines.append(f"- **{f['claim']}**" + (f" _({meta})_" if meta else ""))
            if f.get("falsifier"):
                lines.append(f"  - Wrong if: {f['falsifier']}")
        lines.append("")

    if d["resolved_forecasts"]:
        lines += ["## Resolved forecasts — the receipts", ""]
        for f in d["resolved_forecasts"]:
            out = (f.get("outcome") or "?").upper()
            ev = f" — {f['evidence']}" if f.get("evidence") else ""
            when = f" ({f['resolved_on']})" if f.get("resolved_on") else ""
            lines.append(f"- **{out}**{when}: {f['claim']}{ev}")
        lines.append("")

    if d["stories"]:
        lines += ["## Recent coverage", ""]
        for s in d["stories"]:
            src = f" — {s['source']}" if s.get("source") else ""
            url = f" <{s['url']}>" if s.get("url") else ""
            lines.append(f"- {s['date'] or '—'}{src}: {s['title']}{url}")
        lines.append("")

    fu = d.get("funding")
    if fu:
        lines += ["## Funding signal — independent of news", ""]
        amount = f" · ${fu['total_usd'] / 1e9:.1f}B disclosed" if fu.get("total_usd") else ""
        lines.append(f"{fu['rounds']} round(s) in the last {fu['window_days']} days"
                     f"{amount} · {fu['early']} early / {fu['late']} late")
        if fu.get("read"):
            lines.append(f"_{fu['read']}_")
        for r in fu.get("latest") or []:
            amt = f" (${r['amount_usd'] / 1e6:.0f}M)" if r.get("amount_usd") else ""
            lines.append(f"- {r.get('announced_on') or '—'} — {r.get('company')}: "
                         f"{r.get('round_type')}{amt}")
        lines.append("")

    c = d.get("measured_curve")
    if c:
        lines += [f"## Measured curve — {c['label']} ({c['unit']})", ""]
        lines.append("| Year | Value |")
        lines.append("| --- | --- |")
        for pt in c["series"]:
            lines.append(f"| {pt.get('year')} | {pt.get('value')} |")
        lines.append("")
        if c.get("direction_note"):
            lines.append(f"_{c['direction_note']}_")
        src = c.get("source") or {}
        if src:
            cite = " — ".join(x for x in (src.get("org"), src.get("publication")) if x)
            tail = f" (retrieved {src['retrieved']})" if src.get("retrieved") else ""
            link = f" <{src['url']}>" if src.get("url") else ""
            lines.append(f"Source: {cite}{tail}{link}")
        lines.append("")

    lines += ["---", "", f"**Methodology.** {d['methodology']}", ""]
    return "\n".join(lines).rstrip() + "\n"


# ── PDF renderer (mirrors analytics/strategist.py brief_to_pdf) ───────────────

# Same latin-1 sanitising as strategist.brief_to_pdf — copied rather than
# imported so this pure module never pulls in strategist's Toqan/Supabase deps.
_PDF_REPL = {"—": "-", "–": "-", "→": "->", "↑": "^", "↓": "v", "≤": "<=", "≥": ">=",
             "•": "-", "·": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."}


def _latin1(s) -> str:
    s = "".join(_PDF_REPL.get(ch, ch) for ch in str(s or ""))
    return s.encode("latin-1", "replace").decode("latin-1")


def dossier_to_pdf(d: dict) -> bytes:
    """Render the dossier as a clean PDF (fpdf2, pure-python core fonts)."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    def heading(text, size=13):
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", size)
        pdf.multi_cell(0, size * 0.5, _latin1(text), new_x="LMARGIN", new_y="NEXT")

    def body(text, size=10, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, 5, _latin1(text), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 17)
    pdf.multi_cell(0, 9, _latin1("Lodestar - Technology Dossier"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 14)
    title = d["label"] + (f" ({d['domain']})" if d.get("domain") else "")
    pdf.multi_cell(0, 7, _latin1(title), new_x="LMARGIN", new_y="NEXT")
    body(f"Generated {d['as_of']} - lodestar technology dossier", size=9, style="I")
    pdf.ln(2)

    pl = d["placement"]
    heading("Current placement")
    if not pl["lifecycle_fit"]:
        body(f"Not lifecycle-tracked: {pl.get('lifecycle_note') or 'taxonomy misfit'}")
    elif pl["watching"]:
        body(f"Watching - insufficient evidence ({pl['evidence']} stage-classified "
             f"articles; floor {pl['evidence_floor']}). No stage is claimed.")
    else:
        stage = lambda s: (s or "-").replace("-", " ")  # noqa: E731
        body(f"Maturity (S-curve): {stage(pl['maturity'])}")
        body(f"Adoption (diffusion): {stage(pl['adoption'])}")
        ev = f"Evidence: {pl['evidence']} stage-classified articles (30-day window)"
        if pl["thin_signal"]:
            ev += " - thin signal"
        body(ev)
        if pl["anchored"]:
            vintage = f" ({pl['anchor_as_of']})" if pl.get("anchor_as_of") else ""
            body(f"Anchor: curated stage assessment{vintage} floors this placement.")

    if d["transitions"]:
        heading("Stage-transition history")
        for t in d["transitions"]:
            flags = ", ".join(f for f in (
                "contested" if t["contested"] else "",
                "unconfirmed" if not t["confirmed"] else "",
                "backward" if t["backward"] else "",
            ) if f)
            tail = f" ({flags})" if flags else ""
            body(f"{t['as_of'] or '-'} - {t['dimension']}: {t['from']} -> {t['to']}{tail}")

    if d["open_forecasts"]:
        heading("Open forecasts - what would prove us wrong")
        for f in d["open_forecasts"]:
            body(f.get("claim") or "", size=10, style="B")
            meta = " | ".join(x for x in (
                f"confidence {_pct(f['confidence'])}" if f.get("confidence") is not None else "",
                f"made {f['made_on']}" if f.get("made_on") else "",
                f"resolves by {f['resolve_by']}" if f.get("resolve_by") else "",
            ) if x)
            if meta:
                body(meta, size=8, style="I")
            if f.get("falsifier"):
                body(f"Wrong if: {f['falsifier']}", size=9)

    if d["resolved_forecasts"]:
        heading("Resolved forecasts - the receipts")
        for f in d["resolved_forecasts"]:
            out = (f.get("outcome") or "?").upper()
            when = f" ({f['resolved_on']})" if f.get("resolved_on") else ""
            body(f"{out}{when}: {f.get('claim') or ''}", size=10)
            if f.get("evidence"):
                body(f"Evidence: {f['evidence']}", size=8, style="I")

    if d["stories"]:
        heading("Recent coverage")
        for s in d["stories"]:
            src = f" - {s['source']}" if s.get("source") else ""
            body(f"{s['date'] or '-'}{src}: {s.get('title') or ''}", size=9)
            if s.get("url"):
                body(s["url"], size=7, style="I")

    c = d.get("measured_curve")
    if c:
        heading(f"Measured curve - {c['label']} ({c['unit']})")
        body("  ".join(f"{pt.get('year')}: {pt.get('value')}" for pt in c["series"]), size=9)
        if c.get("direction_note"):
            body(c["direction_note"], size=8, style="I")
        src = c.get("source") or {}
        if src:
            cite = " - ".join(x for x in (src.get("org"), src.get("publication")) if x)
            tail = f" (retrieved {src['retrieved']})" if src.get("retrieved") else ""
            body(f"Source: {cite}{tail}", size=8, style="I")
            if src.get("url"):
                body(src["url"], size=7, style="I")

    heading("Methodology", size=11)
    body(d["methodology"], size=8, style="I")
    return bytes(pdf.output())
