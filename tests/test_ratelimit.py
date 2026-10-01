"""Tests for the per-IP sliding-window rate limiter (backend/app/ratelimit.py).

The window logic is pure given an injected clock; the FastAPI dependency is
exercised through a minimal app, including the X-Forwarded-For keying that
matters behind the platform proxy."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.ratelimit import SlidingWindowLimiter, rate_limit


# ── pure window logic ─────────────────────────────────────────────────────────

def test_allows_up_to_limit_then_blocks():
    lim = SlidingWindowLimiter()
    assert all(lim.allow("k", 3, 60.0, now=t) for t in (0.0, 1.0, 2.0))
    assert not lim.allow("k", 3, 60.0, now=3.0)


def test_window_slides_old_hits_expire():
    lim = SlidingWindowLimiter()
    for t in (0.0, 1.0, 2.0):
        lim.allow("k", 3, 60.0, now=t)
    assert not lim.allow("k", 3, 60.0, now=59.9)
    assert lim.allow("k", 3, 60.0, now=60.0)  # the t=0 hit has aged out


def test_keys_are_independent():
    lim = SlidingWindowLimiter()
    assert lim.allow("a", 1, 60.0, now=0.0)
    assert not lim.allow("a", 1, 60.0, now=1.0)
    assert lim.allow("b", 1, 60.0, now=1.0)  # other client unaffected


# ── FastAPI dependency ────────────────────────────────────────────────────────

def _app(limit=2):
    app = FastAPI()

    @app.post("/hit", dependencies=[Depends(rate_limit("test-scope", limit=limit, window=60))])
    def hit() -> dict:
        return {"ok": True}

    return app


def test_dependency_returns_429_past_limit():
    from backend.app import ratelimit

    ratelimit._limiter.reset()
    client = TestClient(_app(limit=2))
    assert client.post("/hit").status_code == 200
    assert client.post("/hit").status_code == 200
    r = client.post("/hit")
    assert r.status_code == 429
    assert "Too many requests" in r.json()["detail"]


def test_dependency_keys_by_forwarded_for():
    from backend.app import ratelimit

    ratelimit._limiter.reset()
    client = TestClient(_app(limit=1))
    assert client.post("/hit", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert client.post("/hit", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429
    # a different client IP behind the same proxy is not throttled
    assert client.post("/hit", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
