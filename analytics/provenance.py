"""
Signal provenance — the per-field "show your work / cite this" audit trail.

Pure reducers over one stored feed row. When the row carries the per-field
`provenance` map captured at parse time (`home_news/parser.py`), we report exactly
how each field was obtained — agent / keydrift / default / missing — plus a
confidence read over the judgment-loaded fields. Rows that predate the provenance
column degrade to field *coverage* (present / absent): honest about the gap rather
than fabricating confidence. No network, no Streamlit — unit-testable.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Fields shown in the trail, in display order, with a human label. These are the
# judgment-loaded fields an analyst cites; source/date/title/url are the citation.
_TRAIL_FIELDS = [
    ("business_impact", "Materiality"),
    ("scope", "Scope"),
    ("sentiment", "Sentiment"),
    ("companies", "Companies"),
    ("country", "Country"),
]

PROVENANCE_LABEL = {
    "agent": "from source",
    "keydrift": "from source (alt. key)",
    "default": "filled default — not from source",
    "missing": "not provided",
    "present": "present",          # coverage fallback (provenance unknown)
    "absent": "absent",
}
_PROVIDED = ("agent", "keydrift")


def _domain(url: str | None) -> str:
    p = urlparse(url or "")
    # Scheme-less URLs ("example.com/x") land the host in `path`, not `netloc`.
    net = (p.netloc or p.path).lower().split("/")[0]
    return net[4:] if net.startswith("www.") else net


def _display_value(field: str, row: dict) -> str:
    v = row.get(field)
    if field == "companies":
        comps = v or []
        if not comps:
            return "—"
        head = ", ".join(str(c) for c in comps[:4])
        return f"{len(comps)} named: {head}" + (" …" if len(comps) > 4 else "")
    return str(v) if v not in (None, "", []) else "—"


def _coverage(field: str, row: dict) -> str:
    """Fallback when the captured map is absent: present / absent (we can't tell
    agent-supplied from defaulted, so we don't pretend to)."""
    return "present" if row.get(field) not in (None, "", []) else "absent"


def citation(row: dict) -> str:
    """A copy-pasteable citation line for one signal. Pure."""
    title = (row.get("title") or "(untitled)").strip()
    src = row.get("source_name") or _domain(row.get("url")) or "unknown source"
    when = row.get("published_at") or "n.d."
    url = (row.get("url") or "").strip()
    return f'"{title}." {src} ({when}). {url}'.strip()


def signal_provenance(row: dict) -> dict:
    """The 'show your work' audit trail for one signal: what to cite, how each
    judgment field was obtained, and the lens classification trail. Reads the
    captured per-field `provenance` map when present; degrades to coverage."""
    prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else None
    has = prov is not None

    fields = []
    for key, label in _TRAIL_FIELDS:
        p = (prov.get(key) if has else None) or _coverage(key, row)
        fields.append({
            "field": key, "label": label,
            "value": _display_value(key, row),
            "provenance": p,
            "provided": p in _PROVIDED,
        })

    if has:
        provided = sum(1 for f in fields if f["provided"])
        score = provided / len(fields) if fields else 0.0
        conf = ("high" if score >= 0.8 else "medium" if score >= 0.5
                else "low" if score > 0 else "very low")
    else:
        provided, score, conf = None, None, None

    return {
        "has_provenance": has,
        "confidence": conf,
        "score": round(score, 2) if score is not None else None,
        "provided_count": provided,
        "field_count": len(fields),
        "fields": fields,
        "source": {
            "name": row.get("source_name") or _domain(row.get("url")) or "unknown source",
            "domain": _domain(row.get("url")),
            "url": row.get("url"),
            "published_at": row.get("published_at"),
            "feed": row.get("_feed_label") or row.get("feed_label"),
            "feed_icon": row.get("_feed_icon") or row.get("feed_icon"),
        },
        "lens": {
            "classified": bool(row.get("maturity_stage")),
            "rationale": row.get("lens_rationale"),
            "maturity": row.get("maturity_stage"),
            "adoption": row.get("adoption_stage"),
            "move": row.get("strategic_move"),
        },
        "citation": citation(row),
    }
