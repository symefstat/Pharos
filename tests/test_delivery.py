"""Tests for the outbound delivery layer + digest/alert builders (no network)."""

from unittest.mock import MagicMock, patch

import analytics.delivery as dl
from analytics.digest import digest_message, format_transition_alerts, just_confirmed


# ── channel layer ──────────────────────────────────────────────────────────────

def test_send_email_skipped_when_unconfigured(monkeypatch):
    for k in ("DIGEST_EMAILS", "EMAIL_FROM", "RESEND_API_KEY", "SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    assert dl.send_email("s", "b") == "skipped"


def test_send_email_skipped_without_transport(monkeypatch):
    monkeypatch.setenv("DIGEST_EMAILS", "a@example.com")
    monkeypatch.setenv("EMAIL_FROM", "lodestar@example.com")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert dl.send_email("s", "b") == "skipped"


def test_send_email_via_resend(monkeypatch):
    monkeypatch.setenv("DIGEST_EMAILS", "a@example.com, b@example.com")
    monkeypatch.setenv("EMAIL_FROM", "lodestar@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    with patch.object(dl.requests, "post", return_value=MagicMock(status_code=200)) as post:
        assert dl.send_email("Subject", "Body") == "sent"
    kwargs = post.call_args.kwargs
    assert kwargs["json"]["to"] == ["a@example.com", "b@example.com"]
    assert kwargs["headers"]["Authorization"] == "Bearer re_test"


def test_send_email_failure_reports_failed(monkeypatch):
    monkeypatch.setenv("DIGEST_EMAILS", "a@example.com")
    monkeypatch.setenv("EMAIL_FROM", "lodestar@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    with patch.object(dl.requests, "post", side_effect=RuntimeError("boom")):
        assert dl.send_email("s", "b") == "failed"


def test_send_webhook_statuses(monkeypatch):
    monkeypatch.delenv("ALERT_WEBHOOK", raising=False)
    assert dl.send_webhook("hi") == "skipped"
    monkeypatch.setenv("ALERT_WEBHOOK", "https://hooks.example.com/x")
    with patch.object(dl.requests, "post", return_value=MagicMock(status_code=200)):
        assert dl.send_webhook("hi") == "sent"
    with patch.object(dl.requests, "post", side_effect=RuntimeError("boom")):
        assert dl.send_webhook("hi") == "failed"


def test_any_failed():
    assert dl.any_failed({"email": "failed", "webhook": "skipped"})
    assert not dl.any_failed({"email": "sent", "webhook": "skipped"})


def test_app_url(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://lodestar.example.com/")
    assert dl.app_url("/tech/glp-1") == "https://lodestar.example.com/tech/glp-1"
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    assert dl.app_url("/briefing") == "http://localhost:5173/briefing"


# ── transition alert builder ───────────────────────────────────────────────────

TRANS = [
    {"technology": "glp-1", "label": "GLP-1 drugs", "dimension": "adoption",
     "from": "early-adopters", "to": "early-majority", "as_of": "2026-07-09",
     "confirmed": True, "run": 2, "backward": False, "contested": False},
    {"technology": "quantum-computing", "label": "Quantum", "dimension": "maturity",
     "from": "research", "to": "emerging", "as_of": "2026-07-09",
     "confirmed": True, "run": 3, "backward": False, "contested": False},  # settled — no alert
    {"technology": "ev-charging", "label": "EV charging", "dimension": "maturity",
     "from": "emerging", "to": "growth", "as_of": "2026-07-09",
     "confirmed": False, "run": 1, "backward": False, "contested": False},  # pending — no alert
    {"technology": "x", "label": "X", "dimension": "maturity",
     "from": "growth", "to": "emerging", "as_of": "2026-07-09",
     "confirmed": True, "run": 2, "backward": True, "contested": False},   # backward — never
]


def test_just_confirmed_fires_exactly_at_run_2():
    fresh = just_confirmed(TRANS)
    assert [t["technology"] for t in fresh] == ["glp-1"]


def test_format_transition_alerts_deep_links():
    body = format_transition_alerts(just_confirmed(TRANS), "https://app.example.com")
    assert "GLP-1 drugs" in body and "early-adopters → early-majority" in body
    assert "https://app.example.com/tech/glp-1" in body
    assert format_transition_alerts([], "x") == ""


# ── digest builder ─────────────────────────────────────────────────────────────

READ_ROW = {
    "as_of": "2026-07-09",
    "strategic_read": {
        "bottom_line": "AI compute demand shifts pricing power to foundries.",
        "signals": [
            {"title": "Foundry pricing power flips to suppliers", "lens": "market-structure shift",
             "confidence": "high", "action": "defend",
             "action_rationale": "if you design chips, lock multi-year capacity now",
             "falsifier": "Foundry prices reverse or flatten by Q4 2026"},
            {"title": "EV shakeout accelerates", "lens": "market-structure shift",
             "confidence": "high", "action": "exit",
             "action_rationale": "exit before capital burn accelerates",
             "falsifier": "US EV sales growth returns positive by Q3 2026"},
        ],
    },
}


def test_digest_message_carries_spine():
    subject, body = digest_message(READ_ROW, "Internal consistency: 89% …",
                                   TRANS, "https://app.example.com")
    assert subject.startswith("Lodestar briefing 2026-07-09")
    assert "BOTTOM LINE" in body and "pricing power to foundries" in body
    assert "1. Foundry pricing power flips to suppliers" in body
    assert "→ Defend — if you design chips" in body
    assert "✗ Wrong if: Foundry prices reverse" in body
    # the freshly-confirmed transition rides along with its dossier link
    assert "STAGE MOVES CONFIRMED" in body and "/tech/glp-1" in body
    assert "TRUST" in body and "Internal consistency" in body
    assert "https://app.example.com/briefing" in body


def test_digest_message_none_without_read():
    assert digest_message(None, "t", [], "x") is None
    assert digest_message({"strategic_read": {"bottom_line": ""}}, "t", [], "x") is None
