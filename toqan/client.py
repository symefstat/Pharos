"""
Generic Toqan agent client — create-conversation + poll-for-answer.

One `ToqanAgent` wraps one Toqan agent (identified by its API key + display
name). Every agent in Lodestar — the feed extractors, the MOT Lens, the
Strategist — talks to Toqan through this, so the create / poll / retry logic
lives in exactly one place.

Usage:
    from toqan.client import ToqanAgent
    answer = ToqanAgent(api_key, agent_name="MOT Lens Agent").ask(message)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional, Tuple

import requests

from config import Config

logger = logging.getLogger(__name__)

# Overall wait budget for an answer = max_poll_attempts × poll_interval seconds.
# Defaults give 300 × 5s = 25 min, enough headroom for the heaviest agent (the
# Strategist) to finish. Tune per-deploy via env without a code change.
_DEFAULT_MAX_POLL_ATTEMPTS = 300
_DEFAULT_POLL_INTERVAL = 5


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


class ToqanAgent:
    def __init__(
        self,
        api_key: str,
        agent_name: str = "Toqan agent",
        api_url: Optional[str] = None,
        max_poll_attempts: Optional[int] = None,
        poll_interval: Optional[int] = None,
    ):
        if not api_key:
            raise ValueError(f"ToqanAgent ({agent_name}) requires an API key")
        self.api_key = api_key
        self.agent_name = agent_name
        base_url = (api_url or Config.TOQAN_API_URL).rstrip("/")
        self.create_conversation_url = f"{base_url}/api/create_conversation"
        self.get_answer_url = f"{base_url}/api/get_answer"
        # Explicit args win; otherwise env override; otherwise the 25-min default.
        self.max_poll_attempts = (
            max_poll_attempts
            if max_poll_attempts is not None
            else _env_int("TOQAN_MAX_POLL_ATTEMPTS", _DEFAULT_MAX_POLL_ATTEMPTS)
        )
        self.poll_interval = (
            poll_interval
            if poll_interval is not None
            else _env_int("TOQAN_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL)
        )

    def ask(
        self,
        message: str,
        poll_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Send `message` to the agent and return its raw answer string.

        `poll_callback(elapsed_seconds)` is invoked once per poll while waiting,
        so callers (e.g. the UI) can surface live progress.
        """
        conversation_id, request_id = self._create_conversation(message)
        return self._poll_for_answer(conversation_id, request_id, poll_callback)

    def _create_conversation(
        self,
        message: str,
        max_attempts: int = 4,
        backoff: float = 3.0,
    ) -> Tuple[str, str]:
        """Open a conversation, retrying with exponential backoff on failure.

        Creation can fail on a transient network/5xx blip just like polling can,
        so it is retried too — a single hiccup should not abort a whole refresh.
        """
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        last_err: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                resp = requests.post(
                    self.create_conversation_url,
                    headers=headers,
                    json={"user_message": message},
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()
                conversation_id = data.get("conversation_id")
                request_id = data.get("request_id")
                if not conversation_id or not request_id:
                    raise RuntimeError(f"Unexpected create_conversation response: {data}")
                logger.info(
                    "[%s] conversation %s… started, polling for answer",
                    self.agent_name, conversation_id[:8],
                )
                return conversation_id, request_id
            except (requests.exceptions.RequestException, RuntimeError) as e:
                last_err = e
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "[%s] create_conversation attempt %d/%d failed (%s)%s",
                    self.agent_name, attempt + 1, max_attempts, e,
                    f"; retrying in {wait:.0f}s" if attempt < max_attempts - 1 else "",
                )
                if attempt < max_attempts - 1:
                    time.sleep(wait)
        raise RuntimeError(
            f"[{self.agent_name}] create_conversation failed after {max_attempts} attempts: {last_err}"
        )

    def _poll_for_answer(
        self,
        conversation_id: str,
        request_id: str,
        poll_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        headers = {"X-Api-Key": self.api_key}
        params = {"conversation_id": conversation_id, "request_id": request_id}
        start = time.time()

        for attempt in range(self.max_poll_attempts):
            if poll_callback:
                try:
                    poll_callback(int(time.time() - start))
                except Exception:  # never let UI updates break polling
                    pass
            try:
                resp = requests.get(
                    self.get_answer_url, headers=headers, params=params, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.RequestException as e:
                logger.warning(
                    "[%s] poll attempt %d failed (%s), retrying",
                    self.agent_name, attempt + 1, e,
                )
                time.sleep(self.poll_interval)
                continue

            status = data.get("status")
            if status in ("completed", "finished"):
                answer = data.get("answer")
                if not answer:
                    raise RuntimeError(f"[{self.agent_name}] returned empty answer")
                elapsed = int(time.time() - start)
                logger.info(
                    "[%s] answer received after %ds (%d chars)",
                    self.agent_name, elapsed, len(answer),
                )
                return answer
            if status == "failed":
                raise RuntimeError(
                    f"[{self.agent_name}] failed: {data.get('error', 'unknown error')}"
                )
            # processing / pending / queued / in_progress / etc.
            time.sleep(self.poll_interval)

        raise TimeoutError(
            f"[{self.agent_name}] timed out after "
            f"{self.max_poll_attempts * self.poll_interval}s waiting for an answer"
        )
