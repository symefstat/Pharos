"""
Outbound delivery — the channel layer for digests and alerts.

Intelligence that waits in a dashboard doesn't exist for a working analyst; it
has to arrive. This module is the one place that knows HOW to send: email (the
Resend API, falling back to plain SMTP) and a Slack/Discord-style webhook. What
to send is built elsewhere (analytics/digest.py, the *_run.py runners) — the
builders stay pure and unit-tested, this layer does the I/O.

Configuration is entirely .env-driven, and every channel degrades to
logged-not-sent (the ALERT_WEBHOOK pattern alerts_run.py established), so the
runners are safe on a machine with no credentials — they become dry runs:

    RESEND_API_KEY   — Resend (https://resend.com) API key, preferred email path
    SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS — fallback email transport
    EMAIL_FROM       — sender address (required for either email path)
    DIGEST_EMAILS    — comma-separated recipients
    ALERT_WEBHOOK    — Slack/Discord-style webhook ({"text": …}), shared with
                       alerts_run.py / falsifier_run.py
    APP_BASE_URL     — public app origin for deep links (default localhost:5173)
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

import requests

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


def app_url(path: str = "") -> str:
    """Deep link into the app (dossiers, briefing) for outbound messages."""
    base = (os.getenv("APP_BASE_URL") or "http://localhost:5173").rstrip("/")
    return f"{base}{path}"


def email_recipients() -> list[str]:
    return [e.strip() for e in (os.getenv("DIGEST_EMAILS") or "").split(",") if e.strip()]


def _send_via_resend(subject: str, body: str, recipients: list[str], api_key: str) -> bool:
    resp = requests.post(
        _RESEND_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": os.getenv("EMAIL_FROM"), "to": recipients,
              "subject": subject, "text": body},
        timeout=20,
    )
    resp.raise_for_status()
    return True


def _send_via_smtp(subject: str, body: str, recipients: list[str]) -> bool:
    msg = EmailMessage()
    msg["From"] = os.getenv("EMAIL_FROM")
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as s:
        s.starttls()
        user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)
    return True


def send_email(subject: str, body: str) -> str:
    """Send plaintext email to DIGEST_EMAILS via Resend, else SMTP. Returns a
    status — 'sent' | 'skipped' (unconfigured, logged-not-sent) | 'failed'
    (configured but the send blew up). Never raises — a delivery failure must
    never take down the pipeline run around it."""
    recipients = email_recipients()
    if not recipients or not os.getenv("EMAIL_FROM"):
        logger.warning("Email not configured (DIGEST_EMAILS/EMAIL_FROM) — not sent: %s", subject)
        return "skipped"
    try:
        api_key = os.getenv("RESEND_API_KEY")
        if api_key:
            _send_via_resend(subject, body, recipients, api_key)
            return "sent"
        if os.getenv("SMTP_HOST"):
            _send_via_smtp(subject, body, recipients)
            return "sent"
        logger.warning("No email transport (RESEND_API_KEY or SMTP_HOST) — not sent: %s", subject)
        return "skipped"
    except Exception as e:
        logger.error("Email send failed (%s): %s", subject, e)
        return "failed"


def send_webhook(text: str) -> str:
    """POST {"text": …} to ALERT_WEBHOOK (Slack/Discord-style). Same status
    contract as send_email."""
    webhook = os.getenv("ALERT_WEBHOOK")
    if not webhook:
        logger.warning("ALERT_WEBHOOK is not set — not sent:\n%s", text)
        return "skipped"
    try:
        resp = requests.post(webhook, json={"text": text}, timeout=15)
        resp.raise_for_status()
        return "sent"
    except Exception as e:
        logger.error("Webhook post failed: %s", e)
        return "failed"


def deliver(subject: str, body: str) -> dict:
    """Send one message through every configured channel. Returns per-channel
    statuses ({'email': 'sent'|'skipped'|'failed', 'webhook': …}) so runners
    can log honestly and exit non-zero only on a real send failure."""
    return {
        "email": send_email(subject, body),
        "webhook": send_webhook(f"*{subject}*\n\n{body}"),
    }


def any_failed(statuses: dict) -> bool:
    return "failed" in statuses.values()
