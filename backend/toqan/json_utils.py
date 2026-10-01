"""
Shared, drift-tolerant parsers for Toqan agent output.

Agents are told to return bare JSON, but real LLM output sometimes wraps it in
```json fences, a <think>…</think> preamble, a prose sentence, or an object key
like {"items": [...]}. These two helpers strip all of that defensively so the
three call sites (home_news parser, MOT lens, strategist) share one battle-tested
implementation instead of three drifting copies.
"""

from __future__ import annotations

import json
import re
from typing import Optional, Sequence

# Keys an LLM might wrap an array under instead of returning a bare array.
DEFAULT_ARRAY_KEYS: tuple[str, ...] = ("items", "articles", "news", "data", "results", "feed")

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _preprocess(raw: str) -> str:
    """Drop a <think> preamble, then prefer the contents of a ```code fence```."""
    text = _THINK_RE.sub("", raw or "").strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    return text


def parse_json_array(raw: str, keys: Sequence[str] = DEFAULT_ARRAY_KEYS) -> list:
    """Locate and parse a JSON array in an agent answer.

    Tolerates fences, <think> blocks, and prose around the array. Falls back to
    an object that wraps the array under one of `keys` (or a single array-valued
    key). Raises ValueError if no array can be found — callers that want the
    lenient "empty on failure" behaviour should catch it and return [].
    """
    text = _preprocess(raw)

    # 1) Prefer a top-level array (tolerates prose / control chars around it).
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1], strict=False)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass  # fall through to object-wrapper handling

    # 2) Fall back: an object that wraps the array under a known key
    #    (e.g. {"items": [...]}), or a single array-valued key.
    ostart, oend = text.find("{"), text.rfind("}")
    if ostart != -1 and oend != -1 and oend > ostart:
        try:
            obj = json.loads(text[ostart : oend + 1], strict=False)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in agent response: {e}") from e
        if isinstance(obj, dict):
            for k in keys:
                if isinstance(obj.get(k), list):
                    return obj[k]
            arrays = [v for v in obj.values() if isinstance(v, list)]
            if len(arrays) == 1:
                return arrays[0]

    snippet = text[:300] + "…" if len(text) > 300 else text
    raise ValueError(f"Could not locate JSON array in agent response. Got: {snippet!r}")


def parse_json_object(raw: str) -> Optional[dict]:
    """Locate and parse a single JSON object in an agent answer.

    Returns the dict, or None if no parseable object is present (lenient — many
    callers legitimately fall back to treating the answer as markdown prose).
    """
    text = _preprocess(raw)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1], strict=False)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None
