"""
Small resilience helpers for flaky external calls.

The pipeline talks to several best-effort services (yfinance, OpenAI, Supabase)
that can transiently fail or rate-limit. `retry` wraps a call with exponential
backoff so a blip doesn't lose a whole run. Control flow only — the sleep is
injected so it's unit-testable without real delays.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry(fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 1.0,
          label: str = "call", sleep: Callable[[float], None] = time.sleep) -> T:
    """Call `fn`, retrying up to `attempts` times with exponential backoff
    (`base_delay` · 2**i between tries). Returns `fn()`'s value on the first success;
    re-raises the last exception if every attempt fails. `sleep` is injected for tests.

    Use for a single best-effort external call; the caller still decides how to
    degrade if it ultimately raises."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if i + 1 < attempts:
                delay = base_delay * (2 ** i)
                logger.warning("%s failed (attempt %d/%d): %s — retrying in %.1fs",
                               label, i + 1, attempts, e, delay)
                sleep(delay)
    raise last  # type: ignore[misc]
