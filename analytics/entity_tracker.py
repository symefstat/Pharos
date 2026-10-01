"""
Cross-feed entity tracking — follow one company/entity across all feeds.

Hybrid by design so it works immediately:
- **Live feed reads** drive presence-by-feed, per-entity sentiment, and the
  recent-stories list (these have clickable URLs and exist as soon as feeds run).
- **The never-pruned rollup** (`feed_daily_metrics.by_company`) drives the
  long-range mention-volume-over-time chart, which fills in as it accumulates.

Entity names are normalized (see entities.py) so "Google"/"Alphabet"/"DeepMind"
collapse to one canonical entity across feeds.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import date, timedelta

from supabase import Client

from db import get_supabase
from feeds import FEEDS_BY_KEY
from analytics.aggregator import PulseAggregator
from analytics.entities import normalize as normalize_entity
from analytics.weights import article_weight, weighted_companies_in_row, weighted_company_counts

logger = logging.getLogger(__name__)

ROLLUP_TABLE = "feed_daily_metrics"
_SENTIMENTS = ("positive", "negative", "neutral")
# Live feed tables only retain ~14–30 days; cap live look-back accordingly.
_LIVE_MAX_DAYS = 30


def _feed_label(key: str) -> str:
    feed = FEEDS_BY_KEY.get(key)
    return feed.label if feed else (key or "?")


def co_mentions(stories: list[dict], entity: str, top: int = 8) -> list[tuple[str, int]]:
    """Other entities mentioned alongside `entity` in its recent stories — its
    'ecosystem'. Each story's contribution is significance/source-weighted (see
    weights.article_weight) so co-mentions in material, reputable coverage rank
    above incidental ones; the displayed count is rounded. Pure."""
    c: Counter = Counter()
    for s in stories:
        w = article_weight(s)
        for comp in (s.get("companies") or []):
            n = normalize_entity(str(comp))
            if n and n != entity:
                c[n] += w
    return [(name, round(v)) for name, v in c.most_common(top)]


def co_occurrence_matrix(rows: list[dict], top: int = 14) -> dict:
    """Entity↔entity co-occurrence across stories, for a chord diagram (pure).

    Two entities co-occur when they're named in the same story. Returns the top-N
    entities by co-occurrence degree as a symmetric matrix, plus each entity's
    dominant feed (for domain colouring) — so cross-domain bridges show up as
    ribbons spanning colour groups.
    """
    pair: Counter = Counter()
    degree: Counter = Counter()
    by_domain: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        feed = r.get("_feed_label") or r.get("feed_label")  # raw rows vs slim stories
        w = article_weight(r)  # weight edges by significance/source; coloring stays raw presence
        ents = sorted({
            normalize_entity(str(c)) for c in (r.get("companies") or [])
            if normalize_entity(str(c))
        })
        for e in ents:
            if feed:
                by_domain[e][feed] += 1
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                a, b = ents[i], ents[j]
                pair[(a, b)] += w
                degree[a] += w
                degree[b] += w
    if not pair:
        return {"labels": [], "domains": [], "matrix": []}

    labels = [e for e, _ in degree.most_common(top)]  # ranked by weighted degree
    idx = {e: i for i, e in enumerate(labels)}
    n = len(labels)
    matrix = [[0] * n for _ in range(n)]
    for (a, b), c in pair.items():
        if a in idx and b in idx:
            matrix[idx[a]][idx[b]] = round(c)  # weighted edge, rounded for the ribbon/tooltip
            matrix[idx[b]][idx[a]] = round(c)
    domains = [by_domain[e].most_common(1)[0][0] if by_domain[e] else "?" for e in labels]
    return {"labels": labels, "domains": domains, "matrix": matrix}


def domain_convergence(rows: list[dict], min_feeds: int = 2, top_pairs: int = 6,
                       top_seam: int = 6, exclude_feeds=None) -> list[dict]:
    """Convergence radar — name the colliding DOMAINS and who sits at the seam.

    An entity mentioned in stories from ≥`min_feeds` feeds *bridges* those domains
    (the A4 multi-technology signal: convergence is where the next S-curve and the
    next incumbent-disruption play tend to originate). A feed-pair's strength is the
    number of distinct bridging entities (ties broken by total cross-domain mentions);
    for each top pair we name the seam-sitters, ranked by their mentions across the
    two domains. Pure — same `(_feed_label, companies)` data as the co-mention chord.

    `exclude_feeds` (a set of feed labels) drops cross-cutting *lenses* (e.g.
    Disruptive Tech, which spans all sectors by design) so they don't pose as a
    sector pole and bridge everything — leaving genuine sector × sector seams.

    Returns [{domains: (d1, d2), bridges: [{entity, mentions, feeds}], n_bridges,
    strength}], strongest pair first."""
    drop = set(exclude_feeds or ())
    entity_feeds: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        feed = r.get("_feed_label") or r.get("feed_label")
        if not feed or feed in drop:
            continue
        w = article_weight(r)  # significant/reputable bridging coverage weighs more
        ents = {normalize_entity(str(c)) for c in (r.get("companies") or [])}
        for e in ents:
            if e:
                entity_feeds[e][feed] += w

    pair_bridges: dict[tuple, list] = defaultdict(list)
    for e, feeds in entity_feeds.items():
        present = sorted(feeds)  # distinct feeds — the spanning test stays presence-based
        if len(present) < min_feeds:
            continue
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                d1, d2 = present[i], present[j]
                pair_bridges[(d1, d2)].append({
                    "entity": e,
                    "_w": feeds[d1] + feeds[d2],  # unrounded weighted, for sorting only
                    "mentions": round(feeds[d1] + feeds[d2]),
                    "feeds": {d1: round(feeds[d1]), d2: round(feeds[d2])},
                })

    out = []
    for (d1, d2), bridges in pair_bridges.items():
        bridges.sort(key=lambda b: (-b["_w"], b["entity"]))
        strength = round(sum(b["_w"] for b in bridges))
        top = bridges[:top_seam]
        for b in top:
            b.pop("_w", None)
        out.append({
            "domains": (d1, d2),
            "bridges": top,
            "n_bridges": len(bridges),  # count of distinct bridging entities (unweighted)
            "strength": strength,
        })
    out.sort(key=lambda p: (-p["n_bridges"], -p["strength"], p["domains"]))
    return out[:top_pairs]


def interpret_convergence(seams: list[dict]) -> str:
    """Plain-English read of the hottest converging domain pair. Pure."""
    if not seams:
        return ("No cross-domain convergence in the window — named players are staying within "
                "their own domains.")
    top = seams[0]
    d1, d2 = top["domains"]
    names = ", ".join(b["entity"] for b in top["bridges"][:3])
    return (f"**{d1} ✕ {d2}** is the hottest seam — **{top['n_bridges']}** player(s) span both "
            f"domains{f' ({names})' if names else ''}. Convergence is where the next S-curve and "
            "the next incumbent-disruption play tend to originate — watch who's positioned there.")


_CHORD_TEMPLATE = """
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;}
  #wrap{display:flex;flex-direction:column;align-items:center;}
  .lbl{font-size:11px;fill:#24292f;}
  #legend{font-size:11px;color:#57606a;display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:8px;}
  #legend span.item{display:inline-flex;align-items:center;gap:5px;}
  .dot{width:11px;height:11px;border-radius:2px;display:inline-block;}
  #fallback{color:#cf6679;font-size:13px;padding:12px;text-align:center;}
</style></head><body>
<div id="wrap"><svg id="chord"></svg><div id="legend"></div></div>
<div id="fallback" style="display:none">Chord unavailable (could not load D3).</div>
<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
<script>
const DATA = __PAYLOAD__;
(function(){
  if (typeof d3 === 'undefined') { document.getElementById('fallback').style.display='block'; return; }
  const labels=DATA.labels, domains=DATA.domains, matrix=DATA.matrix, colors=DATA.colors;
  const W=760, H=540, outer=Math.min(W,H)/2-120, inner=outer-14;
  const col = i => colors[domains[i]] || '#9aa7b4';
  const svg = d3.select('#chord')
    .attr('viewBox', (-W/2)+' '+(-H/2)+' '+W+' '+H).attr('width','100%').attr('height',H);
  const chords = d3.chord().padAngle(0.045).sortSubgroups(d3.descending)(matrix);
  const arc = d3.arc().innerRadius(inner).outerRadius(outer);
  const ribbon = d3.ribbon().radius(inner);
  svg.append('g').attr('fill-opacity',0.6).selectAll('path').data(chords).join('path')
    .attr('d',ribbon).attr('fill',d=>col(d.source.index))
    .attr('stroke',d=>d3.rgb(col(d.source.index)).darker(0.6))
    .append('title').text(d=>labels[d.source.index]+' ↔ '+labels[d.target.index]+': '+d.source.value);
  const g = svg.append('g').selectAll('g').data(chords.groups).join('g');
  g.append('path').attr('d',arc).attr('fill',d=>col(d.index)).attr('stroke','#fff')
    .append('title').text(d=>labels[d.index]);
  g.append('text').each(function(d){ d.a=(d.startAngle+d.endAngle)/2; })
    .attr('class','lbl').attr('dy','0.35em')
    .attr('transform',d=>'rotate('+(d.a*180/Math.PI-90)+') translate('+(outer+6)+')'+(d.a>Math.PI?' rotate(180)':''))
    .attr('text-anchor',d=>d.a>Math.PI?'end':'start')
    .text(d=>labels[d.index]);
  const seen={}; const leg=d3.select('#legend');
  domains.forEach(dm=>{ if(!seen[dm]){ seen[dm]=1; const s=leg.append('span').attr('class','item');
    s.append('span').attr('class','dot').style('background',colors[dm]||'#9aa7b4'); s.append('span').text(dm); }});
})();
</script></body></html>
"""


def chord_html(data: dict, colors: dict) -> str:
    """Self-contained D3 v7 chord diagram HTML (entities around a ring, ribbons =
    co-mentions, colour = dominant feed). Data is injected as JSON; D3 loads from
    a CDN with a graceful fallback message. Pure string-building."""
    payload = json.dumps({
        "labels": data.get("labels", []), "domains": data.get("domains", []),
        "matrix": data.get("matrix", []), "colors": colors,
    })
    return _CHORD_TEMPLATE.replace("__PAYLOAD__", payload)


def entity_read(entity: str, prof: dict) -> str:
    """One-line dossier read: where it shows up, how much, sentiment posture. Pure."""
    fc = prof.get("feeds_count", 0)
    total = prof.get("total", 0)
    sent = prof.get("sentiment", {})
    pos, neg = sent.get("positive", 0), sent.get("negative", 0)
    by_feed = prof.get("by_feed", {})
    feeds = list(by_feed.keys())
    if fc >= 2:
        where = f"**cross-domain** across **{fc} feeds** ({', '.join(feeds[:3])})"
    elif feeds:
        where = f"concentrated in **{feeds[0]}**"
    else:
        where = "not seen in the live window"
    tone = "positive" if pos > neg else "negative" if neg > pos else "mixed / neutral"
    parts = [f"**{entity}** — {where}; **{total}** recent mentions; "
             f"sentiment skews **{tone}** ({pos} pos / {neg} neg)."]
    if by_feed:
        parts.append(f"Most active in **{max(by_feed, key=by_feed.get)}**.")
    return " ".join(parts)


class EntityTracker:
    def __init__(self, client: Client | None = None):
        self.client = client or get_supabase()
        self.pulse = PulseAggregator(self.client)

    def _rollup_rows(self, days: int) -> list[dict]:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        try:
            return (
                self.client.table(ROLLUP_TABLE)
                .select("feed,metric_date,by_company,by_company_breakdown")
                .gte("metric_date", cutoff)
                .order("metric_date")
                .execute()
                .data
                or []
            )
        except Exception as e:
            logger.warning("EntityTracker: rollup read failed: %s", e)
            return []

    def universe(self, days: int = 30, top: int = 60,
                 weighted: bool = True) -> list[tuple[str, int]]:
        """Candidate entities (canonical name + prominence) for the picker, ranked.

        With `weighted=True` (default) prominence folds the significance/source
        weights (`by_company_breakdown`); counts are rounded to ints for display.
        Prefers the rollup; falls back to live feeds if the rollup is empty (e.g. not
        built yet) — applying the same article-level weight, so the picker's ranking
        matches the dossier's weighted-prominence headline in BOTH states."""
        rollup_rows = self._rollup_rows(days)
        if rollup_rows:
            if weighted:
                c = weighted_company_counts(rollup_rows)
            else:
                c = Counter()
                for r in rollup_rows:
                    for name, n in (r.get("by_company") or {}).items():
                        c[name] += int(n or 0)
            return [(name, round(v)) for name, v in c.most_common(top)]
        # Fallback: rollup not built yet → live feeds. Weight each mention the same
        # way the dossier does (article_weight), so the two views agree.
        c: Counter = Counter()
        for row in self.pulse.all_recent(days=min(days, _LIVE_MAX_DAYS)):
            w = article_weight(row) if weighted else 1.0
            for comp in (row.get("companies") or []):
                nm = normalize_entity(str(comp))
                if nm:
                    c[nm] += w
        return [(name, round(v)) for name, v in c.most_common(top)]

    def profile(self, entity: str, days: int = 30) -> dict:
        """Cross-feed profile for one entity."""
        # Live: presence-by-feed, sentiment, and recent stories (clickable).
        stories: list[dict] = []
        sentiment: Counter = Counter()
        by_feed: Counter = Counter()
        live_weighted = 0.0
        for row in self.pulse.all_recent(days=min(days, _LIVE_MAX_DAYS)):
            norms = {normalize_entity(str(c)) for c in (row.get("companies") or [])}
            if entity in norms:
                slim = PulseAggregator._slim(row)
                stories.append(slim)
                by_feed[slim.get("feed_label") or "?"] += 1
                live_weighted += article_weight(row)
                s = (row.get("sentiment") or "").lower()
                if s in _SENTIMENTS:
                    sentiment[s] += 1

        # Rollup: long-range mention volume over time, per feed (raw counts), plus
        # the entity's weighted prominence over the same window — computed the same
        # way `universe` ranks the picker, so the dossier headline matches the picker.
        series: list[dict] = []
        weighted = 0.0
        rollup_rows = self._rollup_rows(days)
        for r in rollup_rows:
            n = int((r.get("by_company") or {}).get(entity, 0) or 0)
            if n:
                series.append(
                    {"date": str(r.get("metric_date")), "feed": _feed_label(r.get("feed", "")), "count": n}
                )
            for comp, w in weighted_companies_in_row(r):
                if comp == entity:
                    weighted += w
        # Rollup not built yet → fall back to the live weighted prominence, matching
        # the picker's live fallback so the dossier headline doesn't read 0.0 against
        # a non-zero picker count.
        if not rollup_rows:
            weighted = live_weighted

        stories.sort(key=lambda s: str(s.get("published_at") or ""), reverse=True)
        return {
            "entity": entity,
            "by_feed": dict(by_feed.most_common()),
            "feeds_count": len(by_feed),
            "sentiment": dict(sentiment),
            "series": series,
            "stories": stories[:25],
            "total": int(sum(by_feed.values())),     # raw mentions in the live window
            "weighted": weighted,                      # significance/source-weighted prominence (matches picker)
        }
