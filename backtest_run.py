#!/usr/bin/env python3
"""
Backtest runner — replay Lodestar's method over settled technology history.

For each case below: pull historical headlines from the GDELT DOC 2.0 archive
(free, rate-limited — paced at ~6s/request), classify them through the SAME
MOT Lens agent the live product uses, roll up quarterly, and compare the
method's dated stage calls with documented real-world milestones. Results land
in backtest/results/*.json and backtest/BACKTEST_REPORT.md; the Methodology
page serves them via /api/methodology/backtest.

Everything network-derived is cached under backtest/cache/, so re-runs are
free and the study is reproducible without re-spending agent calls:

    python backtest_run.py               # run all cases (fetch → classify → report)
    python backtest_run.py nft-collectibles   # one case
    python backtest_run.py --report-only # rebuild report from caches, no network
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import requests
from dotenv import load_dotenv

logger = logging.getLogger("backtest_run")

ROOT = Path(__file__).parent / "backtest"
CACHE = ROOT / "cache"
RESULTS = ROOT / "results"

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# The API nominally allows one request per 5s, but its limiter penalizes bursts
# for minutes at a time — pace generously and back off hard on a 429.
GDELT_PACE_S = float(os.getenv("GDELT_PACE_S", "20"))
_RETRY_PAUSES = (GDELT_PACE_S, 60.0, 120.0)
PER_QUARTER = 12              # headlines sampled per quarter (post-dedupe)

# ── The cases — settled histories with documented milestones ──────────────────
# Milestone dates are curated judgments; every one carries a public source so a
# reader can dispute the mapping. Notes flag the judgment calls explicitly.
CASES: list[dict] = [
    {
        "key": "mrna-vaccines",
        "label": "mRNA vaccines",
        "query": '"mRNA vaccine"',
        "window": ["2019Q3", "2021Q4"],
        "milestones": [
            {"stage": "emerging", "quarter": "2020Q1",
             "event": "First mRNA COVID-19 vaccine enters human trials (Moderna mRNA-1273, 16 Mar 2020)",
             "source": "https://www.nih.gov/news-events/news-releases/nih-clinical-trial-investigational-vaccine-covid-19-begins"},
            {"stage": "growth", "quarter": "2020Q3",
             "event": "Pivotal Phase 3 trials begin alongside mass-manufacturing commitments (27 Jul 2020)",
             "source": "https://www.nih.gov/news-events/news-releases/phase-3-clinical-trial-investigational-vaccine-covid-19-begins"},
            {"stage": "dominant-design", "quarter": "2020Q4",
             "event": "FDA emergency use authorizations for the Pfizer-BioNTech and Moderna mRNA vaccines (Dec 2020)",
             "source": "https://www.fda.gov/news-events/press-announcements/fda-takes-key-action-fight-against-covid-19-issuing-emergency-use-authorization-first-covid-19"},
        ],
        "notes": None,
    },
    {
        "key": "nft-collectibles",
        "label": "NFTs (digital collectibles)",
        "query": '(NFT OR "non-fungible token")',
        "window": ["2020Q1", "2023Q2"],
        "milestones": [
            {"stage": "growth", "quarter": "2021Q1",
             "event": "Beeple's 'Everydays' sells for $69.3M at Christie's as NFT volume explodes (11 Mar 2021)",
             "source": "https://www.christies.com/about-us/press-archive/details?PressReleaseID=9970"},
            {"stage": "declining", "quarter": "2022Q3",
             "event": "NFT trading volume collapses ~97% from its January peak (Sep 2022)",
             "source": "https://www.bloomberg.com/news/articles/2022-09-28/nft-volumes-tumble-97-from-2022-highs"},
        ],
        "notes": ("Deliberately includes a DECLINE: the method must track collapse, "
                  "not just ascent — 'declining' is a forward move on the axis."),
    },
    {
        "key": "automotive-lidar",
        "label": "Automotive LiDAR",
        "query": 'lidar (automotive OR "self-driving" OR autonomous)',
        "window": ["2019Q1", "2023Q2"],
        "milestones": [
            {"stage": "growth", "quarter": "2020Q4",
             "event": "LiDAR SPAC wave: Velodyne and Luminar list publicly; Luminar-Volvo series-production deal (Q4 2020)",
             "source": "https://www.reuters.com/article/us-luminar-ipo-idUSKBN28D2WD"},
            {"stage": "dominant-design", "quarter": "2023Q1",
             "event": "Sector shakeout: Ouster-Velodyne merger completes after Ibeo insolvency and Quanergy delisting (Feb 2023)",
             "source": "https://www.reuters.com/markets/deals/lidar-makers-ouster-velodyne-complete-merger-2023-02-13/"},
        ],
        "notes": ("Judgment mapping flagged: consolidation/shakeout is read as the "
                  "ferment closing (Utterback–Abernathy), i.e. dominant-design."),
    },
]


# ── GDELT fetch (cached) ───────────────────────────────────────────────────────

def _quarter_bounds(q: str) -> tuple[str, str]:
    y, n = int(q[:4]), int(q[-1])
    m0 = (n - 1) * 3 + 1
    m1 = m0 + 2
    last = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
            7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[m1]
    return f"{y}{m0:02d}01000000", f"{y}{m1:02d}{last}235959"


def _quarters_in(window: list[str]) -> list[str]:
    from analytics.backtest import q_index
    out = []
    qi, end = q_index(window[0]), q_index(window[1])
    while qi <= end:
        out.append(f"{qi // 4}Q{qi % 4 + 1}")
        qi += 1
    return out


def _dedupe_titles(articles: list[dict], cap: int) -> list[dict]:
    seen: set[str] = set()
    out = []
    for a in articles:
        key = "".join((a.get("title") or "").lower().split())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(a)
        if len(out) >= cap:
            break
    return out


def fetch_headlines(case: dict) -> list[dict]:
    """Quarter-by-quarter GDELT pull, cached to backtest/cache. Each headline:
    {url, title, date}. A failed quarter logs and yields nothing — the rollup's
    evidence floor then honestly reports it as below-floor."""
    cache_file = CACHE / f"{case['key']}_headlines.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    out: list[dict] = []
    for q in _quarters_in(case["window"]):
        start, end = _quarter_bounds(q)
        arts: list[dict] = []
        # The API rate-limits hard (429s, or a plain-text scolding with HTTP
        # 200) — pace every request and back off progressively on failure.
        for attempt, pause in enumerate(_RETRY_PAUSES):
            try:
                time.sleep(pause)
                r = requests.get(GDELT_URL, params={
                    "query": f"{case['query']} sourcelang:english",
                    "mode": "artlist", "maxrecords": 50, "format": "json",
                    "startdatetime": start, "enddatetime": end,
                }, timeout=30)
                r.raise_for_status()
                arts = (r.json() or {}).get("articles", []) or []
                break
            except Exception as e:
                if attempt == len(_RETRY_PAUSES) - 1:
                    logger.warning("GDELT %s %s failed after retries: %s", case["key"], q, e)
        kept = _dedupe_titles(arts, PER_QUARTER)
        for a in kept:
            seen = str(a.get("seendate") or "")          # 20210311T120000Z
            date = f"{seen[:4]}-{seen[4:6]}-{seen[6:8]}" if len(seen) >= 8 else None
            if a.get("url") and a.get("title") and date:
                out.append({"url": a["url"], "title": a["title"], "date": date})
        logger.info("%s %s: %d headlines", case["key"], q, len(kept))
    cache_file.write_text(json.dumps(out, indent=1))
    return out


# ── Lens classification (cached) ───────────────────────────────────────────────

def classify_headlines(case: dict, headlines: list[dict]) -> dict[str, dict]:
    """{url: lens fields} via the live MOT Lens agent, cached per case so a
    re-run never re-spends agent calls."""
    cache_file = CACHE / f"{case['key']}_classified.json"
    cached: dict[str, dict] = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    todo = [h for h in headlines if h["url"] not in cached]
    if todo:
        from analytics.lens import LensClassifier

        rows = [{"url": h["url"], "title": h["title"], "summary": "",
                 "companies": [], "tags": []} for h in todo]
        logger.info("%s: classifying %d headlines (%d cached)…",
                    case["key"], len(todo), len(cached))
        cached.update(LensClassifier().classify_in_memory(rows))
        cache_file.write_text(json.dumps(cached, indent=1))
    return cached


# ── Main ───────────────────────────────────────────────────────────────────────

def run_case(case: dict) -> dict:
    from analytics.backtest import build_report

    headlines = fetch_headlines(case)
    classified = classify_headlines(case, headlines)
    items = [{"date": h["date"],
              "maturity_stage": (classified.get(h["url"]) or {}).get("maturity_stage")}
             for h in headlines]
    report = build_report(case, items)
    (RESULTS / f"{case['key']}.json").write_text(json.dumps(report, indent=1))
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_dotenv()
    CACHE.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    report_only = "--report-only" in sys.argv
    cases = [c for c in CASES if not args or c["key"] in args]

    from analytics.backtest import build_report, report_to_markdown

    reports = []
    for case in cases:
        if report_only:
            headlines = (json.loads((CACHE / f"{case['key']}_headlines.json").read_text())
                         if (CACHE / f"{case['key']}_headlines.json").exists() else [])
            classified = (json.loads((CACHE / f"{case['key']}_classified.json").read_text())
                          if (CACHE / f"{case['key']}_classified.json").exists() else {})
            items = [{"date": h["date"],
                      "maturity_stage": (classified.get(h["url"]) or {}).get("maturity_stage")}
                     for h in headlines]
            report = build_report(case, items)
            (RESULTS / f"{case['key']}.json").write_text(json.dumps(report, indent=1))
        else:
            report = run_case(case)
        reports.append(report)
        hits = sum(1 for c in report["comparison"] if c["hit"])
        logger.info("%s: %d/%d milestones called · %d uncorroborated",
                    case["label"], hits, len(report["comparison"]),
                    len(report["false_calls"]))

    generated = datetime.now(timezone.utc).date().isoformat()
    (ROOT / "BACKTEST_REPORT.md").write_text(report_to_markdown(reports, generated))
    logger.info("Report written: backtest/BACKTEST_REPORT.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
