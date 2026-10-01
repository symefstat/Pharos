"""Admin auth gate — token signing, the /login endpoint, and endpoint enforcement.

The Prosus page and the agent-triggering actions are admin-only; the MOT
"Generate analyst's read" scorecard action and job-status polling stay public.
Enforcement lives on the backend, so these tests hit it there (not just the UI).
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import auth
from backend.app.main import app

USER, PW, SECRET = "tester", "s3cret", "unit-test-signing-secret"


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", USER)
    monkeypatch.setenv("ADMIN_PASSWORD", PW)
    monkeypatch.setenv("AUTH_SECRET", SECRET)


@pytest.fixture
def unconfigured(monkeypatch):
    for k in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "AUTH_SECRET", "ADMIN_USERS"):
        monkeypatch.delenv(k, raising=False)


client = TestClient(app)


# ── token signing ────────────────────────────────────────────────────────────
class TestToken:
    def test_mint_verify_roundtrip(self, creds):
        token = auth.mint_token(USER, SECRET)
        assert auth.verify_token(token) == USER

    def test_tampered_token_rejected(self, creds):
        token = auth.mint_token(USER, SECRET)
        assert auth.verify_token(token + "x") is None

    def test_wrong_secret_rejected(self, monkeypatch):
        token = auth.mint_token(USER, SECRET)
        monkeypatch.setenv("ADMIN_USERNAME", USER)
        monkeypatch.setenv("ADMIN_PASSWORD", PW)
        monkeypatch.setenv("AUTH_SECRET", "a-different-secret")
        assert auth.verify_token(token) is None

    def test_expired_token_rejected(self, creds, monkeypatch):
        # exp in the past → rejected.
        monkeypatch.setattr(auth, "TOKEN_TTL_SECONDS", -10)
        token = auth.mint_token(USER, SECRET)
        assert auth.verify_token(token) is None

    def test_verify_fails_closed_when_unconfigured(self, unconfigured):
        # No secret set → nothing verifies, even a structurally valid token.
        token = auth.mint_token(USER, SECRET)
        assert auth.verify_token(token) is None


# ── require_admin dependency ──────────────────────────────────────────────────
class TestRequireAdmin:
    def test_accepts_valid_bearer(self, creds):
        token = auth.mint_token(USER, SECRET)
        assert auth.require_admin(f"Bearer {token}") == USER

    def test_rejects_missing_header(self, creds):
        with pytest.raises(HTTPException) as e:
            auth.require_admin(None)
        assert e.value.status_code == 401

    def test_rejects_non_bearer(self, creds):
        with pytest.raises(HTTPException):
            auth.require_admin("Basic abc")


# ── /api/auth/login ───────────────────────────────────────────────────────────
class TestLogin:
    def test_good_credentials_return_token(self, creds):
        r = client.post("/api/auth/login", json={"username": USER, "password": PW})
        assert r.status_code == 200
        assert auth.verify_token(r.json()["token"]) == USER

    def test_bad_password_401(self, creds):
        r = client.post("/api/auth/login", json={"username": USER, "password": "nope"})
        assert r.status_code == 401

    def test_unconfigured_login_503(self, unconfigured):
        r = client.post("/api/auth/login", json={"username": USER, "password": PW})
        assert r.status_code == 503


# ── endpoint enforcement ──────────────────────────────────────────────────────
class TestEnforcement:
    def test_prosus_requires_auth(self, creds):
        assert client.get("/api/prosus").status_code == 401

    def test_gated_actions_require_auth(self, creds):
        assert client.post("/api/actions/refresh-all").status_code == 401
        assert client.post("/api/actions/strategist").status_code == 401
        assert client.post("/api/actions/classify").status_code == 401
        assert client.post("/api/actions/feed/prosus").status_code == 401

    def test_scorecard_requires_admin(self, creds, monkeypatch):
        # Admin-only since the 2026-07-08 launch review: each call spends LLM
        # budget and upserts a publicly re-served row, so anonymous access meant
        # unbounded cost burn + stored prompt injection.
        monkeypatch.setattr(auth, "verify_token", lambda *_: None)  # ensure no ambient token
        monkeypatch.setattr("backend.app.actions._run_scorecard", lambda *a, **k: None)
        assert client.post("/api/actions/scorecard/Toyota").status_code == 401

    def test_status_polling_is_public(self, creds):
        # Polling must work without a token so pages can track a job started
        # before a session expired. Unknown id returns a payload, not a 401.
        r = client.get("/api/actions/status/does-not-exist")
        assert r.status_code != 401


# ── named multi-user admins (ADMIN_USERS) ─────────────────────────────────────
class TestNamedUsers:
    @pytest.fixture
    def team(self, monkeypatch):
        # These tests log in several times — clear the shared per-IP login
        # limiter so earlier tests' attempts don't 429 these.
        from backend.app.ratelimit import _limiter

        _limiter.reset()
        monkeypatch.delenv("ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        monkeypatch.setenv("ADMIN_USERS", "alice:pw-a,bob:pw-b, malformed , :nopw,noname:")
        monkeypatch.setenv("AUTH_SECRET", SECRET)

    def test_each_named_user_logs_in_with_own_identity(self, team):
        for name, pw in (("alice", "pw-a"), ("bob", "pw-b")):
            r = client.post("/api/auth/login", json={"username": name, "password": pw})
            assert r.status_code == 200
            assert r.json()["username"] == name
            assert auth.verify_token(r.json()["token"]) == name

    def test_wrong_password_and_unknown_user_rejected(self, team):
        assert client.post("/api/auth/login",
                           json={"username": "alice", "password": "pw-b"}).status_code == 401
        assert client.post("/api/auth/login",
                           json={"username": "mallory", "password": "pw-a"}).status_code == 401

    def test_malformed_entries_are_skipped(self, team):
        users = auth._users()
        assert set(users) == {"alice", "bob"}

    def test_legacy_pair_coexists_with_named_users(self, team, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", USER)
        monkeypatch.setenv("ADMIN_PASSWORD", PW)
        r = client.post("/api/auth/login", json={"username": USER, "password": PW})
        assert r.status_code == 200 and r.json()["username"] == USER
        r2 = client.post("/api/auth/login", json={"username": "bob", "password": "pw-b"})
        assert r2.status_code == 200
