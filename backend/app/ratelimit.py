"""
Per-IP rate limiting for the public API surface.

A tiny in-process sliding-window limiter — deliberately dependency-free (no
Redis, no slowapi): the app runs as a single instance (.do/app.yaml
`instance_count: 1`), so process-local state is exact, and at N>1 instances a
per-instance limit still bounds total abuse at N× the configured rate.

What it protects (launch review 2026-07-08, H1):
- POST /api/auth/login — one shared admin credential and no lockout meant
  unlimited brute-force guesses.
- POST /api/ask, /api/ask/stream — each call spends real LLM budget.
- POST /api/refresh — each call drops the warm cache for every user.
- POST /api/actions/* — admin-gated, but a leaked token shouldn't allow
  unbounded background-job spawning either.

`SlidingWindowLimiter.allow` is pure given an injected clock (unit-tested).
"""

from __future__ import annotations

from collections import deque
from threading import Lock
import time

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    """True sliding window: a call is allowed while fewer than `limit` calls
    happened in the trailing `window` seconds for the same key."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, limit: int, window: float, now: float | None = None) -> bool:
        ts = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and ts - q[0] >= window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(ts)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter = SlidingWindowLimiter()


def _client_ip(request: Request) -> str:
    # Behind the platform proxy the peer address is the proxy; the original
    # client is the first hop of X-Forwarded-For (set by DO/Render, not
    # spoofable past their edge).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit: int, window: float = 60.0):
    """FastAPI dependency: at most `limit` calls per `window` seconds per client
    IP for this scope. Use as `dependencies=[Depends(rate_limit("ask", 10))]`."""

    def dependency(request: Request) -> None:
        if not _limiter.allow(f"{scope}:{_client_ip(request)}", limit, window):
            raise HTTPException(
                status_code=429,
                detail="Too many requests — please wait a moment and try again.",
            )

    return dependency
