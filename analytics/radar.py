"""
Radar — horizon scanning for technologies Lodestar does not track yet.

The classifier only sorts stories into *known* registry technologies; everything
else (~70% of ingested stories) is invisible to the tech layer. Radar mines that
discard pile: the Scout agent reads a sample of unmatched stories and proposes
candidate technologies, then DETERMINISTIC code corroborates every proposal
against the full unmatched corpus (mentions, independent sources, feeds, time
spread) before it may surface. Same architecture as the rest of Lodestar: the
agent proposes, evidence gates, a human promotes — a candidate only becomes
tracked when an admin clicks "start tracking" (the self-serve flow), where the
normal evidence floor applies.

Without TOQAN_SCOUT the deterministic fallback surfaces topical tag themes
(coarser, but the page never goes dark). Pure functions (unmatched, sample,
pack/parse, corroborate, fallback) are unit-tested; run_radar hits Supabase.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ENV_KEY = "TOQAN_SCOUT"
CANDIDATES_TABLE = "radar_candidates"
SCANS_TABLE = "radar_scans"
PROMPT_VERSION = "scout-v3"

# Corroboration gate — a proposal only surfaces when the full unmatched corpus
# independently supports it. Mirrors the spirit of the placement evidence floor.
MIN_MENTIONS = 5      # distinct stories whose text contains a candidate keyword
MIN_SOURCES = 3       # distinct publishers
MIN_SPREAD_DAYS = 7   # first-seen → last-seen (sustained, not a one-day splash)
# Research gate — papers lead news by years, so a candidate may surface on the
# arXiv stream alone: sustained recurrence across abstracts, flagged
# research-stage so the page never presents it as market-confirmed.
MIN_PAPERS = 3

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_POLL_ATTEMPTS = int(os.getenv("TOQAN_SCOUT_MAX_POLL_ATTEMPTS", "").strip() or 90)

# Event-shaped tags carry no technology identity — excluded from the fallback.
_EVENT_TAGS = frozenset({
    "regulation", "policy", "m&a", "funding", "contract", "deal", "deals",
    "launch", "product-launch", "milestone", "sales", "earnings", "approval",
    "trial", "tariff", "tariffs", "conflict", "procurement", "breakthrough",
    "partnership", "expansion", "lawsuit", "ipo", "restructuring", "guidance",
    "acquisition", "investment", "hiring", "layoffs", "banking", "geopolitics",
})


def slugify(label: str) -> str:
    return _SLUG_RE.sub("-", (label or "").strip().lower()).strip("-")


def strip_thinking(raw: str) -> str:
    return _THINK_RE.sub("", raw or "").strip()


def trim_why(text: str, n: int = 300) -> str:
    """Cap the scout's rationale at a WORD boundary (pure) — a mid-word cut
    reads as a bug, not a summary."""
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",;:-—– ") + "…"


def unmatched(rows: list[dict], techs) -> list[dict]:
    """Stories that match NO tracked technology (pure) — the Radar corpus."""
    from analytics.tech_layer import match_technologies

    return [r for r in rows if not match_technologies(r, techs)]


def sample_stories(rows: list[dict], n: int = 90) -> list[dict]:
    """The unmatched stories the Scout reads (pure): newest first, deduped by
    title, material-impact stories boosted so weak-signal noise doesn't crowd
    out the stories most likely to name a real technology."""
    seen: set[str] = set()
    out: list[dict] = []
    # newest first within each impact band, material stories ahead of the rest
    ordered = sorted(rows, key=lambda r: str(r.get("published_at") or ""), reverse=True)
    ordered.sort(key=lambda r: str(r.get("business_impact") or "").lower() != "material")
    for r in ordered:
        key = str(r.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= n:
            break
    return out


def build_scout_pack(stories: list[dict], tracked_labels: list[str],
                     domains: list[str], papers: list[dict] | None = None,
                     brief: str | None = None) -> str:
    """The pack the Scout reasons over (pure): what we already track (so it
    never re-proposes it), the domain vocabulary, the numbered unmatched
    stories, and — numbered CONTINUOUSLY after them — recent research
    abstracts. One [S#] space keeps citation validation simple; the section
    header tells the Scout which items are research-stage evidence.

    With a `brief`, the scan is DIRECTED: the analyst asked a question, and the
    Scout must propose only candidates responsive to it (rule inlined here so
    behavior holds even before a prompt re-paste)."""
    lines: list[str] = []
    if brief:
        lines += [
            "=== FOCUS BRIEF (directed scan) ===",
            f"The analyst asked: {brief.strip()}",
            "Propose ONLY candidates responsive to this brief. If nothing in the",
            "evidence answers it, return [] — never pad with off-brief candidates.",
            "",
        ]
    lines += [
        "=== ALREADY TRACKED (never propose these or close variants) ===",
        " · ".join(tracked_labels),
        "",
        f"=== DOMAIN VOCABULARY === {', '.join(domains)}, or 'other'",
        "",
        "=== UNMATCHED NEWS STORIES (cite as [S#]) ===",
    ]

    def fmt(i: int, s: dict) -> str:
        date = str(s.get("published_at") or "")[:10] or "?"
        src = s.get("source_name") or s.get("_feed_label") or "?"
        title = str(s.get("title") or "").strip()
        summary = str(s.get("summary") or "").strip()
        return f"[S{i}] ({date}, {src}) {title}" + (f" — {summary}" if summary else "")

    for i, s in enumerate(stories, 1):
        lines.append(fmt(i, s))
    if papers:
        lines += ["", "=== RESEARCH ABSTRACTS (arXiv — same [S#] numbering; a candidate",
                  "seen here but not in the news is RESEARCH-STAGE, which is valuable) ==="]
        for j, p in enumerate(papers, len(stories) + 1):
            lines.append(fmt(j, p))
    lines += ["", "Propose candidate technologies per your instructions (STRICT JSON)."]
    return "\n".join(lines)


def parse_scout(raw: str, n_stories: int) -> list[dict]:
    """Parse + validate the Scout's JSON (pure). Tolerates a <think> trace and
    code fences; drops any candidate with a phantom [S#], missing fields, or
    fewer than 2 cited stories. Returns [] rather than raising — Radar must
    fail open to the deterministic fallback."""
    text = strip_thinking(raw)
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        items = json.loads(text[start:end + 1])
    except Exception:
        return []
    if not isinstance(items, list):
        return []

    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        why = str(it.get("why") or "").strip()
        keywords = [str(k).strip().lower() for k in (it.get("keywords") or [])
                    if str(k).strip()]
        try:
            cited = sorted({int(s) for s in (it.get("stories") or [])})
        except Exception:
            continue
        if not (2 <= len(name) <= 60) or not keywords or len(keywords) > 6:
            continue
        if len(cited) < 2 or any(not (1 <= s <= n_stories) for s in cited):
            continue  # phantom or under-cited — never surfaces
        out.append({
            "name": name,
            "keywords": keywords[:6],
            "domain_hint": str(it.get("domain_hint") or "other").strip() or "other",
            "why": trim_why(why),
            "cited": cited,
        })
    return out[:8]


def _kw_res(kws: list[str]) -> list[re.Pattern]:
    """Word-boundary patterns for candidate keywords (pure). Substring matching
    let 'tempo' hit 'temporal' and hand a payments candidate 30 phantom physics
    papers — boundaries keep the evidence honest. Plural 's' tolerated."""
    return [re.compile(r"\b" + re.escape(k) + r"s?\b", re.IGNORECASE) for k in kws]


def _keyword_hits(kws: list[str], rows: list[dict]) -> list[dict]:
    res = _kw_res(kws)
    out = []
    for r in rows:
        hay = " ".join([
            str(r.get("title") or ""), str(r.get("summary") or ""),
            " ".join(str(t) for t in (r.get("tags") or [])),
        ])
        if any(p.search(hay) for p in res):
            out.append(r)
    return out


def _spread_days(dates: list[str]) -> int:
    if len(dates) < 2:
        return 0
    try:
        return (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days
    except ValueError:
        return 0


def weekly_counts(dates: list[str], weeks: int = 4) -> list[int]:
    """Mentions bucketed into trailing 7-day windows, oldest→newest (pure).
    Anchored to the newest date in the input, so the result is deterministic
    from the data alone. Feeds the per-card momentum bars."""
    days = []
    for d in dates:
        try:
            days.append(datetime.fromisoformat(d[:10]))
        except ValueError:
            continue
    if not days:
        return [0] * weeks
    anchor = max(days)
    out = [0] * weeks
    for d in days:
        offset = (anchor - d).days // 7  # 0 = newest week
        if 0 <= offset < weeks:
            out[weeks - 1 - offset] += 1
    return out


def adjacency(kws: list[str], all_rows: list[dict], techs,
              min_n: int = 2, top: int = 2) -> list[dict]:
    """Which tracked technologies this candidate co-occurs with (pure): count
    stories across the FULL feed (matched ones included) that contain a
    candidate keyword AND match a tracked technology. Answers "new theme, or
    offshoot of something we already watch?" with plain counting."""
    from analytics.tech_layer import match_technologies

    by_key = {t.key: t for t in techs}
    res = _kw_res(kws)
    counts: Counter = Counter()
    for r in all_rows:
        hay = " ".join([
            str(r.get("title") or ""), str(r.get("summary") or ""),
            " ".join(str(t) for t in (r.get("tags") or [])),
        ])
        if not any(p.search(hay) for p in res):
            continue
        for key in match_technologies(r, techs):
            counts[key] += 1
    return [{"tech": k, "label": by_key[k].label, "n": n}
            for k, n in counts.most_common(top) if n >= min_n and k in by_key]


def tracked_counts(all_rows: list[dict], all_papers: list[dict], techs) -> list[dict]:
    """Evidence coordinates for every tracked technology (pure): stories/30d
    and arXiv papers/30d on the SAME axes the candidates are measured on —
    the reference dots of the emergence map."""
    from analytics.tech_layer import match_technologies

    stories: Counter = Counter()
    papers: Counter = Counter()
    for r in all_rows:
        for key in match_technologies(r, techs):
            stories[key] += 1
    for p in all_papers:
        for key in match_technologies(p, techs):
            papers[key] += 1
    return [{"tech": t.key, "label": t.label, "domain": t.domain,
             "stories": stories.get(t.key, 0), "papers": papers.get(t.key, 0)}
            for t in techs]


def _receipts(rows: list[dict], n: int = 6) -> list[dict]:
    top = sorted(rows, key=lambda r: str(r.get("published_at") or ""), reverse=True)[:n]
    return [{
        "title": str(r.get("title") or "")[:200],
        "url": r.get("url"),
        "source": r.get("source_name"),
        "date": str(r.get("published_at") or "")[:10],
    } for r in top]


def corroborate(candidate: dict, corpus: list[dict],
                papers: list[dict] | None = None) -> dict | None:
    """Evidence-gate one proposal (pure). The agent's word is never enough: a
    candidate surfaces only via the NEWS gate (≥MIN_MENTIONS stories from
    ≥MIN_SOURCES publishers over ≥MIN_SPREAD_DAYS) or the RESEARCH gate
    (≥MIN_PAPERS arXiv abstracts over ≥MIN_SPREAD_DAYS — papers lead news, so
    a paper-only candidate is exactly what Radar exists to catch; it carries
    `research_stage: true` so the page never presents it as market-confirmed).
    Returns the stored evidence dict, or None when both gates fail."""
    kws = [k for k in candidate.get("keywords", []) if len(k) >= 3]
    if not kws:
        return None
    hits = _keyword_hits(kws, corpus)
    paper_hits = _keyword_hits(kws, papers or [])
    sources = {r.get("source_name") for r in hits if r.get("source_name")}
    feeds = {r.get("_feed_label") for r in hits if r.get("_feed_label")}
    news_dates = sorted({str(r.get("published_at") or "")[:10] for r in hits
                         if r.get("published_at")})
    paper_dates = sorted({str(r.get("published_at") or "")[:10] for r in paper_hits
                          if r.get("published_at")})

    news_ok = (len(hits) >= MIN_MENTIONS and len(sources) >= MIN_SOURCES
               and _spread_days(news_dates) >= MIN_SPREAD_DAYS)
    research_ok = (len(paper_hits) >= MIN_PAPERS
                   and _spread_days(paper_dates) >= MIN_SPREAD_DAYS)
    if not news_ok and not research_ok:
        return None

    all_dates = sorted(news_dates + paper_dates)
    return {
        "mentions": len(hits),
        "sources": len(sources),
        "feeds": sorted(f for f in feeds if f),
        "papers": len(paper_hits),
        "research_stage": research_ok and not news_ok,
        "first_seen": all_dates[0],
        "last_seen": all_dates[-1],
        # momentum: every mention (news + papers), trailing weekly buckets
        "weekly": weekly_counts([str(r.get("published_at") or "")[:10]
                                 for r in hits + paper_hits if r.get("published_at")]),
        "stories": _receipts(hits),
        "paper_items": _receipts(paper_hits, n=4),
    }


def dedupe_against_registry(candidates: list[dict], techs) -> list[dict]:
    """Drop proposals that duplicate a tracked technology (pure): same slug,
    or any keyword overlapping a tracked keyword/label in either direction."""
    tracked_kws = {kw for t in techs for kw in t.keywords}
    tracked_kws |= {t.label.lower() for t in techs}
    keys = {t.key for t in techs}

    def dupe(c: dict) -> bool:
        if slugify(c["name"]) in keys:
            return True
        for k in c["keywords"]:
            if any(k in tk or tk in k for tk in tracked_kws):
                return True
        return False

    return [c for c in candidates if not dupe(c)]


def fallback_candidates(corpus: list[dict], max_out: int = 8) -> list[dict]:
    """No-agent fallback (pure): recurring topical tags in the unmatched corpus,
    event-shaped tags excluded. Coarser than the Scout (themes, not named
    technologies) but keeps Radar alive without a key."""
    tags = Counter(
        str(t).strip().lower() for r in corpus for t in (r.get("tags") or [])
        if str(t).strip() and str(t).strip().lower() not in _EVENT_TAGS
    )
    out = []
    for tag, _n in tags.most_common(max_out * 3):
        if len(tag) < 3:
            continue
        out.append({
            "name": tag.replace("-", " ").title(),
            "keywords": [tag, tag.replace("-", " ")],
            "domain_hint": "other",
            "why": "Recurring theme in stories outside every tracked technology "
                   "(deterministic tag scan — set TOQAN_SCOUT for named candidates).",
            "cited": [],
        })
        if len(out) >= max_out:
            break
    return out


# Tokens too generic to establish identity between candidate names — "agent"
# alone must not merge "enterprise AI agents" into "AI-agent payments".
_GENERIC_TOKENS = frozenset({
    "technology", "technologie", "tech", "system", "network", "platform",
    "solution", "infrastructure", "agent", "model", "digital", "smart",
})


def match_existing(c: dict, stored: list[dict]) -> str | None:
    """The stored candidate this proposal is a re-naming of, if any (pure).
    The Scout re-proposes the same thing under fresh names across scans
    ("NGSO mega-constellation networks" → "LEO satellite megaconstellations"),
    so identity is judged on substance: an identical label, an EXACTLY shared
    keyword (plural tolerated), or ≥2 shared specific name tokens.

    Among eligible rows the BEST match wins, never the first: a stablecoin
    proposal once shared one keyword ('machine payments') with the agent-
    payments candidate and hijacked its row while the true stablecoin row —
    same label, two shared keywords — sat further down the list. Deliberately
    conservative on eligibility (a duplicate card is dismissable; a wrong
    merge silently loses a candidate); returns the key so the row is UPDATED."""
    def norm(s: str) -> str:
        return slugify(s).rstrip("s")

    def toks(s: str) -> set[str]:
        return {w.rstrip("s") for w in slugify(s).split("-")
                if len(w) > 2 and w.rstrip("s") not in _GENERIC_TOKENS}

    c_kws = {norm(k) for k in c.get("keywords", [])}
    c_name = slugify(c.get("name", ""))
    c_toks = toks(c.get("name", ""))
    best_key, best_score = None, 0
    for ex in stored:
        ex_kws = {norm(str(k)) for k in (ex.get("keywords") or [])}
        ex_label = str(ex.get("label") or ex.get("key") or "")
        shared = len(c_kws & ex_kws)
        tok = len(c_toks & toks(ex_label))
        label_eq = bool(c_name) and c_name == slugify(ex_label)
        if not (label_eq or shared >= 1 or tok >= 2):
            continue
        score = (100 if label_eq else 0) + shared * 10 + tok
        if score > best_score:
            best_key, best_score = str(ex["key"]), score
    return best_key


DETECTION_WINDOW_DAYS = 90


def detection_call_fields(label: str, key: str, ev: dict, today: str) -> dict:
    """The _mk() kwargs for a Radar detection call (pure) — locked at the
    moment of promotion, so Radar itself earns a graded track record. The
    claim is deliberately about DURABILITY, not a fast start: 90 days on, is
    this still above the placement evidence floor, or was it a splash?
    Confidence scales modestly with the evidence that earned the promotion."""
    mentions = ev.get("mentions") or 0
    sources = ev.get("sources") or 0
    papers = ev.get("papers") or 0
    confidence = min(0.75, 0.55 + (0.10 if mentions >= 20 else 0)
                     + (0.05 if sources >= 10 else 0)
                     + (0.05 if papers >= MIN_PAPERS else 0))
    receipts = f"{mentions} stories · {sources} publishers" + \
               (f" · {papers} papers" if papers else "")
    falsifier = ("below the placement evidence floor (or no placement snapshot) "
                 f"{DETECTION_WINDOW_DAYS} days after promotion")
    return {
        "kind": "radar_detection",
        "subject": key,
        "claim": (f"Radar detection stands: ‘{label}’ still clears the placement "
                  f"evidence floor {DETECTION_WINDOW_DAYS} days after promotion "
                  f"(surfaced {ev.get('first_seen', '?')} on {receipts}) "
                  f"— wrong if: {falsifier}"),
        "horizon": "short",
        "confidence": confidence,
        "basis": f"radar candidate promoted {today}: {receipts}"
                 + (" · research-stage" if ev.get("research_stage") else ""),
        "params": {"falsifier": falsifier, "radar_key": key,
                   "promoted_on": today, "evidence_at_promotion": {
                       "mentions": mentions, "sources": sources, "papers": papers,
                       "first_seen": ev.get("first_seen"),
                       "found_via": ev.get("found_via")}},
        "as_of": today,
        "resolve_days": DETECTION_WINDOW_DAYS,
        "fp_basis": f"radar_detection|{key}|{today}",
        "source": "radar",
    }


def should_resurface(old_signal: int, new_signal: int) -> bool:
    """Whether a dismissed candidate has outgrown its dismissal (pure): the
    combined signal (stories + papers) must at least DOUBLE since the admin's
    verdict AND grow by ≥5 absolute — small-number noise never resurfaces."""
    return new_signal >= 2 * max(1, old_signal) and new_signal - old_signal >= 5


def store_candidate(client, ckey: str, c: dict, ev: dict, today: str,
                    set_status: str | None = None) -> None:
    """Insert a new candidate, or refresh an existing one's evidence. Existing
    rows are UPDATEd (never upserted): a PostgREST upsert checks NOT NULL on
    the proposed row before conflict resolution, so omitting first_detected
    fails — and an admin's dismissed/promoted status must survive re-scans
    (`set_status` overrides only for the explicit resurfacing path)."""
    row = {
        "key": ckey,
        "label": c["name"],
        "keywords": c["keywords"],
        "domain_hint": c["domain_hint"],
        "why": c["why"],
        "evidence": ev,
        "prompt_version": PROMPT_VERSION,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    if set_status:
        row["status"] = set_status
    existing = (client.table(CANDIDATES_TABLE).select("key,status")
                .eq("key", ckey).execute().data or [])
    if existing:
        client.table(CANDIDATES_TABLE).update(row).eq("key", ckey).execute()
    else:
        row.setdefault("status", "new")
        row["first_detected"] = today
        client.table(CANDIDATES_TABLE).insert(row).execute()


def run_radar(client, rows: list[dict], techs, *, api_key: str | None = None,
              log=None, brief: str | None = None) -> dict:
    """Full scan: mine → propose (Scout, fail-open) → dedupe → corroborate →
    upsert. Never overwrites an admin's dismissed/promoted status. Returns
    counts for the job log.

    With a `brief`, the scan is directed: the Scout answers the analyst's
    question over the same evidence. No tag fallback in that mode — tag themes
    can't answer a question, and a directed scan without a Scout key is an
    honest error, not a degraded result."""
    say = log or (lambda m, ok=True: logger.info(m))
    corpus = unmatched(rows, techs)
    say(f"Radar corpus: {len(corpus)} of {len(rows)} stories match no tracked technology")
    if not corpus:
        return {"surfaced": 0, "proposed": 0, "rejected": 0, "corpus": 0, "papers": 0}

    # Research stream (arXiv) — the leading signal. Fail-open: an outage costs
    # this scan its research gate, never the scan. RADAR_ARXIV=0 disables.
    papers: list[dict] = []
    all_papers: list[dict] = []
    if os.getenv("RADAR_ARXIV", "").strip() != "0":
        try:
            from analytics.arxiv_feed import fetch_recent

            all_papers = fetch_recent()
            papers = unmatched(all_papers, techs)
            say(f"arXiv research stream: {len(papers)} recent abstracts outside tracked tech")
        except Exception as e:
            say(f"arXiv stream skipped: {e}", ok=False)

    key = api_key or os.getenv(ENV_KEY)
    if brief and not key:
        raise RuntimeError(f"a directed scan needs the Scout agent — set {ENV_KEY}")
    proposals: list[dict] = []
    if key:
        try:
            from toqan.client import ToqanAgent

            stories = sample_stories(corpus)
            paper_sample = sample_stories(papers, n=40)
            from technologies import known_domains

            pack = build_scout_pack(stories, [t.label for t in techs], known_domains(),
                                    papers=paper_sample, brief=brief)
            agent = ToqanAgent(api_key=key, agent_name="Scout Agent",
                               max_poll_attempts=_MAX_POLL_ATTEMPTS)
            proposals = parse_scout(agent.ask(pack), len(stories) + len(paper_sample))
            say(f"Scout proposed {len(proposals)} candidates"
                + (f" for brief: {brief}" if brief else ""))
        except Exception as e:
            if brief:
                raise  # a directed scan must not silently answer a different question
            # A CONFIGURED Scout that fails is a transient outage — skip this
            # scan rather than degrade stored candidates to coarse tag themes
            # (an outage once overwrote a named candidate with its tag theme).
            say(f"Scout unavailable ({e}) — skipping this scan; candidates keep "
                "their last good evidence until the next refresh", ok=False)
            return {"surfaced": 0, "proposed": 0, "rejected": 0,
                    "corpus": len(corpus), "papers": len(papers)}
    # Tag-theme fallback ONLY when no Scout is configured at all — a degraded
    # mode the page labels, never a substitute for a temporarily failing agent.
    if not proposals and not brief and not key:
        proposals = fallback_candidates(corpus)
        say(f"Deterministic fallback: {len(proposals)} tag themes")

    proposals = dedupe_against_registry(proposals, techs)
    # the Scout renames the same idea across scans — resolve against what's
    # already stored so re-detections refresh one row instead of piling up
    try:
        stored = (client.table(CANDIDATES_TABLE)
                  .select("key,label,keywords,status,evidence").execute().data or [])
    except Exception:
        stored = []
    today = datetime.now(timezone.utc).date().isoformat()
    surfaced = rejected = 0
    for c in proposals:
        # a re-detection refreshes the stored row on the UNION of keywords —
        # each scan's naming adds recall, never shrinks it
        prior = match_existing(c, stored)
        ex = next((s for s in stored if str(s["key"]) == prior), None) if prior else None
        if ex:
            c["keywords"] = list(dict.fromkeys(
                [*c["keywords"], *(str(k).lower() for k in ex.get("keywords") or [])]
            ))[:8]
            say(f"↻ '{c['name']}' is already on the radar as '{prior}' — refreshing it")
        ev = corroborate(c, corpus, papers)
        if not ev:
            rejected += 1
            say(f"— '{c['name']}' failed the evidence gate "
                f"(needs ≥{MIN_MENTIONS} stories/≥{MIN_SOURCES} sources/"
                f"≥{MIN_SPREAD_DAYS}d, or ≥{MIN_PAPERS} papers/≥{MIN_SPREAD_DAYS}d)")
            continue
        if brief:
            ev["found_via"] = trim_why(brief, 120)
        # which tracked technologies this candidate co-occurs with (full feed,
        # matched stories included — the radar corpus excludes them by design)
        ev["adjacent"] = adjacency(c["keywords"], rows, techs)
        # dismissal with memory: a dismissed candidate that has clearly outgrown
        # the evidence it was dismissed on comes back for a fresh decision
        set_status = None
        if ex and ex.get("status") == "dismissed":
            old_ev = ex.get("evidence") or {}
            old_sig = old_ev.get("dismissed_signal")
            if old_sig is None:
                old_sig = (old_ev.get("mentions") or 0) + (old_ev.get("papers") or 0)
            new_sig = ev["mentions"] + (ev.get("papers") or 0)
            if should_resurface(int(old_sig), new_sig):
                set_status = "new"
                ev["resurfaced"] = {"was": int(old_sig), "now": new_sig,
                                    "dismissed_at": old_ev.get("dismissed_at")}
                say(f"⤴ '{c['name']}' resurfaced — evidence {old_sig} → {new_sig} "
                    "since it was dismissed")
        ckey = prior or slugify(c["name"])
        if not ckey:
            continue
        try:
            store_candidate(client, ckey, c, ev, today, set_status=set_status)
            if not prior:  # same-scan re-namings must merge too
                stored.append({"key": ckey, "label": c["name"], "keywords": c["keywords"]})
            surfaced += 1
            say(f"✓ {c['name']}: {ev['mentions']} stories · {ev['sources']} sources"
                + (f" · {ev['papers']} papers" if ev.get("papers") else "")
                + (" · research-stage" if ev.get("research_stage") else "")
                + f" · since {ev['first_seen']}")
        except Exception as e:
            say(f"✗ {c['name']}: {e}", ok=False)

    stats = {"surfaced": surfaced, "proposed": len(proposals), "rejected": rejected,
             "corpus": len(corpus), "papers": len(papers)}
    _log_scan(client, stats, brief, tracked_counts(rows, all_papers, techs))
    return stats


def _log_scan(client, stats: dict, brief: str | None,
              coords: list[dict] | None = None) -> None:
    """One radar_scans row per scan — feeds the page's transparency strip and
    the emergence map's tracked reference dots. Fail-open twice over: a
    missing tracked_coords column drops the coords and retries, a missing
    table costs the strip, never the scan."""
    row = {
        "brief": (brief or None),
        "corpus": stats["corpus"],
        "papers": stats["papers"],
        "proposed": stats["proposed"],
        "surfaced": stats["surfaced"],
        "rejected": stats["rejected"],
    }
    try:
        try:
            client.table(SCANS_TABLE).insert({**row, "tracked_coords": coords or []}).execute()
        except Exception as e:
            if "tracked_coords" not in str(e):
                raise
            logger.warning("radar_scans.tracked_coords missing — apply "
                           "'SQL Tables/radar_scans_tracked_coords.sql' for the map.")
            client.table(SCANS_TABLE).insert(row).execute()
    except Exception as e:
        logger.warning("Radar scan log unavailable (%s) — apply "
                       "'SQL Tables/radar_scans.sql' for the scan strip.", e)


def last_scan(client) -> dict | None:
    """Most recent scan-log row, or None (also when the table is missing)."""
    try:
        rows = (client.table(SCANS_TABLE).select("*")
                .order("at", desc=True).limit(1).execute().data or [])
        return rows[0] if rows else None
    except Exception:
        return None


def detect_graduations(history_rows: list[dict], today: str,
                       floor: int | None = None) -> list[dict]:
    """Technologies whose FIRST at-or-above-the-evidence-floor snapshot is
    today (pure) — the graduation moment: watching → a real dot on the S-curve.
    Firing only on the first such snapshot makes the alert once-only without a
    state table; long-established techs graduated in the past and never fire."""
    if floor is None:
        from analytics.tech_layer import EVIDENCE_FLOOR
        floor = EVIDENCE_FLOOR
    by_tech: dict[str, list[dict]] = {}
    for h in history_rows:
        if h.get("technology"):
            by_tech.setdefault(h["technology"], []).append(h)
    out = []
    for tech, rows in by_tech.items():
        placed = [r for r in rows
                  if r.get("maturity_stage") and (r.get("article_count") or 0) >= floor]
        if not placed:
            continue
        first = min(placed, key=lambda r: str(r.get("as_of") or ""))
        if str(first.get("as_of") or "")[:10] == today:
            out.append({"technology": tech, "label": first.get("label") or tech,
                        "stage": first.get("maturity_stage"),
                        "articles": first.get("article_count") or 0, "as_of": today})
    return sorted(out, key=lambda g: g["label"])


def format_graduations(grads: list[dict], base_url: str) -> str:
    """Alert body for graduations (pure) — one block per technology, with the
    Radar provenance called out when the dot started as a detection."""
    lines = []
    for g in grads:
        origin = " Surfaced by Radar before it had a stage." if g.get("from_radar") else ""
        lines.append(
            f"{g['label']} earned its place on the S-curve — first placed at "
            f"‘{g['stage']}’ with {g['articles']} stage-classified articles.{origin}\n"
            f"{base_url}/tech/{g['technology']}"
        )
    return "\n\n".join(lines)


def list_candidates(client, include_dismissed: bool = False) -> list[dict]:
    """Stored candidates, newest evidence first. Missing table → [] (the page
    shows the setup hint)."""
    try:
        q = client.table(CANDIDATES_TABLE).select("*")
        if not include_dismissed:
            q = q.neq("status", "dismissed")
        return q.order("last_updated", desc=True).limit(50).execute().data or []
    except Exception as e:
        logger.warning("Radar candidates unavailable (%s) — apply "
                       "'SQL Tables/radar_candidates.sql'.", e)
        return []
