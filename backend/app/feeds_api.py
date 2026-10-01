"""
/api/feeds — the 📰 Feeds tab: the latest classified stories per feed. Mirrors
Home.py render_feeds()/render_feed(), but sourced from the shared recent-rows
aggregate (grouped by feed) so it needs no per-table reads.

/api/ask — the 💬 Ask tab: a conversational analyst over the feeds + MOT theory
(analytics.ask.AskLodestar). Degrades to a clear "not configured" message when
TOQAN_ASK isn't set.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import data
from .ratelimit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feeds"])


@router.get("/api/feeds")
def feeds() -> dict:
    from feeds import FEEDS

    rows = data.rows(days=30)
    by_feed: dict[str, list[dict]] = {}
    for r in rows:
        key = r.get("_feed_key") or r.get("_feed_label") or "?"
        by_feed.setdefault(key, []).append(r)

    out = []
    for f in FEEDS:
        stories = by_feed.get(f.key, [])
        stories = sorted(stories, key=lambda s: s.get("published_at") or "", reverse=True)
        out.append(
            {
                "key": f.key,
                "label": f.label,
                "icon": getattr(f, "icon", ""),
                "count": len(stories),
                "stories": stories[:48],
            }
        )
    return {"feeds": out}


class HistoryTurn(BaseModel):
    """One prior chat turn. A strict schema (instead of a free-form dict) keeps
    arbitrary keys/roles out of the prompt pack the LLM agent receives."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryTurn] = Field(default=[], max_length=20)

    def history_dicts(self) -> list[dict]:
        return [t.model_dump() for t in self.history]


# Each Ask call spends real LLM budget and holds a worker thread for up to the
# Ask poll budget — a per-IP cap bounds anonymous cost/DoS exposure (H1).
_ASK_LIMIT = [Depends(rate_limit("ask", limit=10, window=60))]


@router.post("/api/ask", dependencies=_ASK_LIMIT)
def ask(body: AskBody) -> dict:
    if not os.getenv("TOQAN_ASK"):
        return {
            "configured": False,
            "answer": (
                "Ask isn't configured. Set `TOQAN_ASK` in `.env` (create the agent from "
                "`Agents_prompt/Ask_Lodestar_Agent.md`) to enable conversational answers "
                "over the feeds + MOT theory."
            ),
            "stories": [],
            "theory": [],
        }
    try:
        from analytics.ask import AskLodestar

        res = AskLodestar(data._supabase()).answer(body.question, history=body.history_dicts())
        return {
            "configured": True,
            "answer": res.get("answer", ""),
            "thinking": res.get("thinking", ""),
            "stories": res.get("stories", []),
            "theory": res.get("theory", []),
        }
    except Exception:
        # Log the real error; never echo internals (paths, keys, stack text) to the public.
        logger.exception("Ask failed")
        return {"configured": True,
                "answer": "Couldn't answer right now — please try again in a moment.",
                "stories": [], "theory": []}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/api/ask/stream", dependencies=_ASK_LIMIT)
def ask_stream(body: AskBody) -> StreamingResponse:
    """Server-Sent-Events variant of /api/ask: streams the retrieval stages and a
    live 'reasoning' tick timer, then a final `done` event with the answer,
    reasoning trace, and sources. Powers the Ask page's live-thinking view."""

    def gen():
        if not os.getenv("TOQAN_ASK"):
            yield _sse({
                "type": "done", "configured": False,
                "answer": ("Ask isn't configured. Set `TOQAN_ASK` in `.env` (create the agent "
                           "from `Agents_prompt/Ask_Lodestar_Agent.md`) to enable answers."),
                "thinking": "", "stories": [], "theory": [],
            })
            return
        try:
            from analytics.ask import AskLodestar

            ab = AskLodestar(data._supabase())
            for ev in ab.answer_events(body.question, history=body.history_dicts()):
                if ev.get("type") == "done":
                    ev["configured"] = True
                yield _sse(ev)
        except Exception:
            logger.exception("Ask stream failed")
            yield _sse({"type": "error",
                        "message": "Couldn't answer right now — please try again in a moment."})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
