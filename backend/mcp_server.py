#!/usr/bin/env python3
"""
Lodestar MCP server — the product's reads as tools for Claude and other agents.

Makes Lodestar infrastructure, not just a destination: an agent (Claude Code,
Claude Desktop, Toqan, anything MCP-speaking) can pull the tracked-technology
list, a full dossier, today's briefing, and the graded track record. Read-only
by design — nothing here can trigger agents, write rows, or grade forecasts.

It wraps the running HTTP API (so it works against localhost or the deployed
instance, with no database credentials in this process):

    LODESTAR_API_URL   backend origin (default http://localhost:8000)

Run (stdio transport — what MCP clients expect):

    ./venv/bin/python backend/mcp_server.py

Claude Code registration:

    claude mcp add lodestar -- ./venv/bin/python backend/mcp_server.py
"""

# NOTE: no `from __future__ import annotations` — mcp 1.9.4's tool
# introspection needs real (non-string) annotations to build schemas.
import os

import httpx
from mcp.server.fastmcp import FastMCP

API = (os.getenv("LODESTAR_API_URL") or "http://localhost:8000").rstrip("/")

mcp = FastMCP(
    "lodestar",
    instructions=(
        "Read-only access to Lodestar, a technology & market intelligence product: "
        "tracked technologies with lifecycle stages, per-technology dossiers "
        "(evidence, forecasts with falsifiers, graded outcomes), the daily "
        "strategist briefing, and the accountable forecast ledger. All data is "
        "news-derived and carries its own confidence flags — repeat them, never "
        "launder them away."
    ),
)


def _get(path: str) -> dict:
    r = httpx.get(f"{API}{path}", timeout=60)
    r.raise_for_status()
    return r.json()


@mcp.tool()
def list_technologies() -> list[dict]:
    """Every tracked technology with its current lifecycle read: key (use with
    get_dossier), label, domain, maturity/adoption stage, whether it is merely
    'watching' (below the evidence floor — no stage claim), and 30d coverage."""
    payload = _get("/api/mot")
    return [{
        "key": t.get("tech"),
        "label": t.get("label"),
        "domain": t.get("domain"),
        "maturity": None if t.get("watching") else t.get("maturity"),
        "adoption": None if t.get("watching") else t.get("adoption"),
        "watching": bool(t.get("watching")),
        "articles_30d": t.get("coverage"),
    } for t in payload.get("technologies", []) if t.get("tech")]


@mcp.tool()
def get_dossier(tech_key: str) -> dict:
    """The full dossier for one technology (see list_technologies for keys):
    placement with evidence counts and anchor, analyst read, stage-transition
    history, key players, open forecasts WITH their falsifiers, resolved
    outcomes, capital moves, funding signal, and recent stories."""
    d = _get(f"/api/mot/tech/{tech_key}")
    d.pop("methodology", None)          # boilerplate — keep the payload lean
    return d


@mcp.tool()
def get_briefing() -> dict:
    """Today's strategist briefing: the bottom line, decisive signals (each
    with action, falsifier, confidence, and dossier links), cross-domain
    convergence, what-to-watch, and the honest calibration tagline."""
    p = _get("/api/briefing")
    strategist = p.get("strategist") or {}
    read = strategist.get("read") or {}
    return {
        "as_of": strategist.get("as_of"),
        "calibration": (p.get("calibration") or {}).get("tagline"),
        "bottom_line": read.get("bottom_line"),
        "confidence": read.get("confidence"),
        "signals": read.get("signals") or [],
        "convergence": read.get("convergence") or [],
        "watch": read.get("watch") or [],
    }


@mcp.tool()
def get_track_record() -> dict:
    """The accountable forecast ledger, summarized: world-graded vs
    internal-consistency records (never conflate them), per-category scorecard,
    and the most recent resolved calls with outcomes. Full ledger with
    fingerprints: GET /api/ledger on the API itself."""
    lg = _get("/api/ledger")
    rows = lg.get("forecasts") or []
    resolved = [r for r in rows if r.get("status") == "resolved"][:20]
    return {
        "stats": lg.get("stats"),
        "records_by_basis": lg.get("records_by_basis"),
        "policy": lg.get("policy"),
        "recent_resolved": [{
            "claim": r.get("claim"),
            "outcome": r.get("outcome"),
            "confidence": r.get("confidence"),
            "category": r.get("category"),
            "made_on": r.get("made_on"),
            "resolved_on": r.get("resolved_on"),
            "evidence": r.get("evidence"),
        } for r in resolved],
        "open_count": sum(1 for r in rows if r.get("status") == "open"),
    }


if __name__ == "__main__":
    mcp.run()
