"""
/api/methodology/* — data behind the Methodology page's evidence sections.

The backtest study (backtest_run.py) writes its per-technology results to
backtest/results/*.json in the repo; this router serves them to the page. The
files ship with the deployment, so the endpoint is a plain read — no DB, no
agents. An empty list means the study hasn't been run/committed yet and the
page simply omits the section.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/methodology", tags=["methodology"])

_RESULTS_DIR = Path(__file__).resolve().parents[2] / "backtest" / "results"


@router.get("/backtest")
def backtest() -> dict:
    """Every backtest case result, misses and false calls included."""
    reports = []
    try:
        for f in sorted(_RESULTS_DIR.glob("*.json")):
            try:
                reports.append(json.loads(f.read_text()))
            except Exception as e:
                logger.warning("Unreadable backtest result %s: %s", f.name, e)
    except Exception:
        pass
    hits = sum(1 for r in reports for c in r.get("comparison", []) if c.get("hit"))
    total = sum(len(r.get("comparison", [])) for r in reports)
    return {
        "reports": reports,
        "summary": {
            "cases": len(reports),
            "milestones": total,
            "hits": hits,
            "false_calls": sum(len(r.get("false_calls", [])) for r in reports),
        },
    }
