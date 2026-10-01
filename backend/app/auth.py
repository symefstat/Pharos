"""
/api/auth/* — a minimal shared-admin gate for the live deployment.

The app is public, but two things must be admin-only:
  • the agent-triggering actions (they fire live Toqan/LLM agents), and
  • the Prosus page (sensitive portfolio data).

Enforcement is on the backend so a direct `curl` is blocked too — hiding the
buttons in the SPA is not enough. Credentials come from env — the legacy single
pair (ADMIN_USERNAME / ADMIN_PASSWORD) and/or named per-person users
(ADMIN_USERS="alice:pw1,bob:pw2") — plus a server secret (AUTH_SECRET) used to
sign a self-contained bearer token, so there is no session store to manage.
Named users mean a teammate gets their own revocable credential and actions
carry their identity (the token `sub`), instead of everyone sharing one login.

Token format:  b64url(payload_json) + "." + b64url(hmac_sha256(payload, secret))
where payload = {"sub": <username>, "exp": <unix seconds>}. The SPA keeps the
token in sessionStorage (so it dies with the browser tab); the `exp` here is a
12-hour safety backstop, not the primary session lifetime.

Fails closed: if the credentials or AUTH_SECRET are unset, every protected
endpoint denies access rather than opening up.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import time
from hashlib import sha256

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from .ratelimit import rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 12h backstop; the real "until browser close" lifetime is enforced client-side
# by storing the token in sessionStorage.
TOKEN_TTL_SECONDS = 12 * 60 * 60


def _users() -> dict[str, str]:
    """{username: password} — the legacy single pair plus ADMIN_USERS entries
    ("alice:pw1,bob:pw2"). A malformed entry is skipped, never a crash."""
    out: dict[str, str] = {}
    user = os.getenv("ADMIN_USERNAME", "")
    pw = os.getenv("ADMIN_PASSWORD", "")
    if user and pw:
        out[user] = pw
    for pair in os.getenv("ADMIN_USERS", "").split(","):
        if ":" not in pair:
            continue
        name, upw = pair.split(":", 1)
        if name.strip() and upw:
            out[name.strip()] = upw
    return out


def _config() -> tuple[dict[str, str], str] | None:
    """({username: password}, secret) from env, or None when auth is unset —
    fails closed: no users or no secret means no one can log in."""
    users = _users()
    secret = os.getenv("AUTH_SECRET", "")
    if users and secret:
        return users, secret
    return None


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: bytes, secret: str) -> str:
    return _b64e(hmac.new(secret.encode(), payload, sha256).digest())


def mint_token(username: str, secret: str) -> str:
    payload = json.dumps(
        {"sub": username, "exp": int(time.time()) + TOKEN_TTL_SECONDS},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"{_b64e(payload)}.{_sign(payload, secret)}"


def verify_token(token: str | None) -> str | None:
    """Return the username if the token is valid & unexpired, else None."""
    cfg = _config()
    if not cfg or not token:
        return None
    secret = cfg[1]
    try:
        body_b64, sig = token.split(".", 1)
        payload = _b64d(body_b64)
    except Exception:  # malformed token
        return None
    if not hmac.compare_digest(sig, _sign(payload, secret)):
        return None
    try:
        claims = json.loads(payload)
    except Exception:
        return None
    if not isinstance(claims, dict) or int(claims.get("exp", 0)) < int(time.time()):
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) else None


def require_admin(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: 401 unless a valid `Authorization: Bearer <token>`."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    sub = verify_token(token)
    if not sub:
        raise HTTPException(status_code=401, detail="admin authentication required")
    return sub


class LoginBody(BaseModel):
    username: str
    password: str


# Admin credentials with no lockout — a per-IP cap is the only brute-force
# protection, so it is deliberately tight (H1).
@router.post("/login", dependencies=[Depends(rate_limit("login", limit=5, window=60))])
def login(body: LoginBody) -> dict:
    cfg = _config()
    if not cfg:
        # Admin auth isn't set up on this deployment — no one can log in.
        raise HTTPException(status_code=503, detail="admin login is not configured")
    users, secret = cfg
    # Constant-time compare against the matching user's password; unknown
    # usernames compare against a dummy so timing never confirms an account.
    expected = users.get(body.username, "\x00missing")
    ok_user = body.username in users
    ok_pw = hmac.compare_digest(body.password, expected)
    if not (ok_user and ok_pw):
        raise HTTPException(status_code=401, detail="invalid username or password")
    return {"token": mint_token(body.username, secret), "username": body.username}


@router.get("/me")
def me(authorization: str | None = Header(default=None)) -> dict:
    """Validate a stored token on SPA load."""
    username = require_admin(authorization)
    return {"username": username}
