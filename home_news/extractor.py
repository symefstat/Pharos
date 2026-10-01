"""
Toqan caller for the feed news agents.

Thin wrapper over the generic `toqan.client.ToqanAgent`: it adds the feed-news
default prompt and preserves the `fetch_raw(user_message, poll_callback)`
interface the pipeline already uses. New code should prefer `ToqanAgent`
directly; this stays so the feed runner keeps its familiar entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from toqan.client import ToqanAgent


class HomeNewsExtractor:
    def __init__(self, api_key: str, api_url: str, agent_name: str):
        self.agent = ToqanAgent(api_key=api_key, api_url=api_url, agent_name=agent_name)
        self.agent_name = agent_name

    def fetch_raw(
        self,
        user_message: Optional[str] = None,
        poll_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Call the agent and return its raw JSON-string answer.

        `poll_callback(elapsed_seconds)` is invoked once per poll while waiting,
        so callers can surface live progress.
        """
        today = datetime.now().date().isoformat()
        message = user_message or (
            f"Generate the home news feed for {today}. "
            "Return up to 15 items as a JSON array per your instructions. "
            "Output ONLY the JSON array — no surrounding text."
        )
        return self.agent.ask(message, poll_callback=poll_callback)
