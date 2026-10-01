"""Tests for the retry resilience helper (net.py) — sleep injected, no real delays."""

import pytest

from net import retry


def test_retry_returns_on_first_success():
    calls = []
    assert retry(lambda: (calls.append(1), "ok")[1], sleep=lambda _: None) == "ok"
    assert len(calls) == 1


def test_retry_succeeds_after_transient_failures():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    slept = []
    assert retry(flaky, attempts=3, base_delay=2.0, sleep=slept.append) == "ok"
    assert state["n"] == 3
    assert slept == [2.0, 4.0]   # exponential backoff between the two retries; none after success


def test_retry_reraises_after_exhausting_attempts():
    def always_fail():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        retry(always_fail, attempts=2, sleep=lambda _: None)


def test_retry_rejects_bad_attempts():
    with pytest.raises(ValueError):
        retry(lambda: 1, attempts=0)
