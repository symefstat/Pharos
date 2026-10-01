"""
Digest & alert builders — pure message assembly for outbound delivery.

The daily briefing digest and the stage-transition alert are plaintext (email
body and Slack webhook share it), built entirely from arguments so everything
here is unit-testable with fixtures. Sending lives in analytics/delivery.py;
the runners (digest_run.py, transition_alerts_run.py) glue the two together.
"""

from __future__ import annotations


def _truncate(text: str | None, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def just_confirmed(transitions: list[dict]) -> list[dict]:
    """The transitions that confirmed on the CURRENT snapshot (run == 2): the
    destination stage's second consecutive reading is the moment a pending move
    becomes a confirmed one, so alerting on it notifies exactly once. Backward
    moves (near-impossible re-estimation noise) never alert. Pure."""
    return [t for t in transitions
            if t.get("confirmed") and t.get("run") == 2 and not t.get("backward")]


def format_transition_alerts(transitions: list[dict], app_base: str) -> str:
    """One alert block for freshly-confirmed stage transitions, deep-linked to
    each technology's dossier page. Pure; '' when there is nothing to say."""
    if not transitions:
        return ""
    lines = ["🔬 Stage transition confirmed"
             if len(transitions) == 1 else
             f"🔬 {len(transitions)} stage transitions confirmed"]
    for t in transitions:
        stage = f"{t.get('dimension')}: {t.get('from')} → {t.get('to')}"
        flag = " · contested" if t.get("contested") else ""
        lines.append(f"• {t.get('label')} — {stage} (as of {t.get('as_of')}){flag}")
        # Agent-written catalyst line (Transition Explainer), when one was produced.
        if t.get("why"):
            lines.append(f"  Why: {t['why']}")
        lines.append(f"  Dossier: {app_base}/tech/{t.get('technology')}")
    return "\n".join(lines)


def digest_message(read_row: dict | None, tagline: str,
                   transitions: list[dict], app_base: str,
                   max_signals: int = 5) -> tuple[str, str] | None:
    """(subject, body) for the daily briefing digest, or None when there is no
    strategist read to send — a digest with nothing in it must not be sent.

    The body mirrors what makes the Briefing worth reading: the bottom line,
    each decisive signal WITH its action and falsifier (the product's spine),
    any freshly-confirmed stage moves, and the honest trust line. Pure."""
    read = (read_row or {}).get("strategic_read") or {}
    bottom = str(read.get("bottom_line") or "").strip()
    if not bottom:
        return None
    as_of = str((read_row or {}).get("as_of") or "")[:10]
    signals = (read.get("signals") or [])[:max_signals]

    parts = [f"LODESTAR BRIEFING — {as_of}", "", "BOTTOM LINE", bottom]

    if signals:
        parts += ["", f"DECISIVE SIGNALS ({len(signals)})"]
        for i, s in enumerate(signals, 1):
            conf = str(s.get("confidence") or "").strip()
            lens = str(s.get("lens") or "").strip()
            meta = " · ".join(x for x in (lens, f"{conf} confidence" if conf else "") if x)
            parts.append(f"{i}. {s.get('title')}" + (f"  [{meta}]" if meta else ""))
            action = str(s.get("action") or "").strip()
            if action:
                rationale = _truncate(s.get("action_rationale"), 220)
                parts.append(f"   → {action.capitalize()}" + (f" — {rationale}" if rationale else ""))
            falsifier = str(s.get("falsifier") or "").strip()
            if falsifier:
                parts.append(f"   ✗ Wrong if: {_truncate(falsifier, 220)}")

    fresh = just_confirmed(transitions)
    if fresh:
        parts += ["", "STAGE MOVES CONFIRMED"]
        for t in fresh:
            parts.append(f"• {t.get('label')}: {t.get('dimension')} "
                         f"{t.get('from')} → {t.get('to')} — {app_base}/tech/{t.get('technology')}")

    if tagline:
        parts += ["", "TRUST", tagline.replace("**", "")]

    parts += ["", f"Full briefing: {app_base}/briefing",
              f"Track record: {app_base}/ledger"]

    subject = f"Lodestar briefing {as_of} — {_truncate(bottom, 90)}"
    return subject, "\n".join(parts)
