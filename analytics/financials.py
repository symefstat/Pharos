"""
Financial reducers over the enriched company snapshots + daily price series.

Pure: no network, no Streamlit. The numbers arrive from ``finance.client``
(yfinance) via the ``financials_run`` job into Supabase; this module turns them
into MOT reads:

  • rd_intensity / investment_signal — E1: who is plowing revenue back into the
    next S-curve vs harvesting the current one.
  • event_reaction / deal_reactions — did the market actually re-price on a deal we
    tagged 'material'? A measured check on the business_impact label.

Chart builders return single-layer Altair specs (safe to render headlessly);
reducers return plain structures. Missing numbers stay None — never coerced to 0.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from statistics import median

import altair as alt
import pandas as pd

logger = logging.getLogger(__name__)

# R&D / revenue thresholds for the templated read (rough, deliberately coarse).
_RD_HEAVY = 0.15
_RD_MODERATE = 0.06


def rd_intensity(revenue, rd_expense) -> float | None:
    """R&D / revenue, or None if either is missing or revenue is non-positive."""
    try:
        r = float(revenue)
        d = float(rd_expense)
    except (TypeError, ValueError):
        return None
    if r <= 0 or d < 0:
        return None
    return d / r


def investment_signal(rd_intensity_value) -> str:
    """One-word E1 posture from R&D intensity."""
    if rd_intensity_value is None:
        return "unknown"
    if rd_intensity_value >= _RD_HEAVY:
        return "R&D-heavy"
    if rd_intensity_value >= _RD_MODERATE:
        return "moderate"
    return "harvesting"


def _to_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def event_reaction(event_date, prices: list[dict], window: int = 3) -> dict | None:
    """Approximate event study: % change in close from the last trading day *strictly
    before* `event_date` to `window` trading days later.

    The baseline is the close BEFORE the event — not the announcement-day close, which
    already absorbs the news (look-ahead leakage that makes a same-day-absorbed move
    read as a "shrug"). So the window captures the announcement-day reaction itself.

    `prices` = [{date, close}] for one ticker (any order). None if there's no pre-event
    baseline in the series or not enough forward data."""
    ev = _to_date(event_date)
    if not ev or not prices:
        return None
    series = sorted(
        (
            {"d": d, "c": float(p["close"])}
            for p in prices
            if (d := _to_date(p.get("date"))) is not None and p.get("close") is not None
        ),
        key=lambda x: x["d"],
    )
    if not series:
        return None

    base_i = None
    for i, p in enumerate(series):
        if p["d"] < ev:           # strictly before — the pre-announcement baseline
            base_i = i
        else:
            break
    if base_i is None:
        return None

    post_i = min(base_i + window, len(series) - 1)
    if post_i == base_i:
        return None  # event too recent — no forward data yet
    pre, post = series[base_i]["c"], series[post_i]["c"]
    if pre <= 0:
        return None
    return {
        "pre": pre,
        "post": post,
        "pct": round((post - pre) / pre * 100.0, 1),
        "base_date": series[base_i]["d"].isoformat(),
        "post_date": series[post_i]["d"].isoformat(),
        "trading_days": post_i - base_i,
    }


def classify_reaction(pct, threshold: float = 2.0) -> str:
    """Direction of the move vs a materiality threshold (%): up / down / flat."""
    if pct is None:
        return "unknown"
    if pct >= threshold:
        return "up"
    if pct <= -threshold:
        return "down"
    return "flat"


def deal_reactions(rows, prices_by_symbol, ticker_for, window: int = 3,
                   threshold: float = 2.0) -> list[dict]:
    """Measured price reaction per *material* deal EVENT, deduped on
    (symbol, event_date). The same story lands in several feed tables by design
    (cross-feed corroboration), but the measured ±window is identical for every
    copy — extra rows would repeat the same reaction verbatim and inflate the
    event-study counts ("N of M deals"). One event = one row; the first-seen
    article is the representative. `ticker_for(name)->Ticker|None` and the
    price map are injected to keep this pure. Sorted by |move| desc. One
    (first mapped) company per story."""
    from analytics.mot_analyst import _is_capital_row

    out = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        if str(r.get("business_impact") or "").lower() != "material":
            continue
        if not _is_capital_row(r):
            continue
        for comp in (r.get("companies") or []):
            tk = ticker_for(str(comp))
            if not tk:
                continue
            series = prices_by_symbol.get(tk.symbol)
            if not series:
                continue
            event_date = str(r.get("published_at") or "")[:10]
            if (tk.symbol, event_date) in seen:
                break  # same company, same event window — a cross-feed copy
            rx = event_reaction(r.get("published_at"), series, window=window)
            if rx:
                seen.add((tk.symbol, event_date))
                out.append({
                    "company": tk.entity,
                    "symbol": tk.symbol,
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "feed": r.get("_feed_label"),
                    "pct": rx["pct"],
                    "direction": classify_reaction(rx["pct"], threshold),
                    "event_date": event_date,       # when the deal hit
                    "base_date": rx["base_date"],   # the pre-event baseline (day before)
                    "post_date": rx["post_date"],
                })
            break  # only the first mapped company per story
    out.sort(key=lambda x: abs(x["pct"]), reverse=True)
    return out


def summarize_reactions(reactions: list[dict], threshold: float = 2.0) -> str:
    """One-line read: how many 'material' deals the market actually moved on."""
    if not reactions:
        return "No priced material deals to check in the window."
    moved = sum(1 for r in reactions if r["direction"] in ("up", "down"))
    shrugged = len(reactions) - moved
    txt = (f"**{moved} of {len(reactions)}** material deals moved the stock "
           f"≥{threshold:.0f}% within a few days")
    if shrugged:
        txt += f"; **{shrugged}** the market shrugged at (tagged material, price barely moved)"
    return txt + ". _A measured check on the business-impact label._"


def consensus_divergence(reactions: list[dict]) -> dict:
    """'Consensus vs. reality' — the contrarian screen. Each reaction is a deal OUR
    lens tagged *material*; the market either re-priced it (`confirmed` — consensus
    agrees) or shrugged (`shrugged` — price flat, a divergence between our read and
    the market). The shrugged set is the signal: material-by-our-lens developments
    the market hasn't paid for — candidate mispricings (or labels to interrogate).

    The split keys off each reaction's pre-computed `direction` (classified in
    `deal_reactions`, the single source of the materiality threshold). Shrugged are
    sorted most-ignored first (smallest move = widest gap); confirmed biggest-move
    first. Pure. Returns the two lists + counts + divergence rate."""
    confirmed = sorted((r for r in reactions if r.get("direction") in ("up", "down")),
                       key=lambda r: abs(r.get("pct") or 0), reverse=True)
    shrugged = sorted((r for r in reactions if r.get("direction") == "flat"),
                      key=lambda r: abs(r.get("pct") or 0))
    n = len(confirmed) + len(shrugged)
    return {
        "confirmed": confirmed,
        "shrugged": shrugged,
        "n": n,
        "n_confirmed": len(confirmed),
        "n_shrugged": len(shrugged),
        "divergence_rate": round(len(shrugged) / n, 3) if n else None,
    }


def interpret_divergence(div: dict, threshold: float = 2.0) -> str:
    """Plain-English contrarian read of the consensus-vs-reality split — honest about
    the dual reading (a real edge, OR a materiality label that's too loose)."""
    n = div.get("n", 0)
    if not n:
        return "No priced material deals in the window yet to test against the market."
    s = div.get("n_shrugged", 0)
    deals = "deal" if n == 1 else "deals"
    if s == 0:
        return (f"The market re-priced on **all {n}** {deals} we tagged material — consensus and "
                "our read agree; no contrarian gaps in the window.")
    rate = (div.get("divergence_rate") or 0) * 100
    return (f"**{s} of {n}** {deals} we called material drew a market shrug (<{threshold:.0f}% move "
            f"in ~3 days) — a **{rate:.0f}% divergence**. These are the contrarian watch items: "
            "developments our lens reads as material that the market hasn't paid for — an edge if "
            "the market is slow, a label to interrogate if it isn't.")


def _close_on_or_before(series, target):
    """Last close on/before date `target` from an ascending [{date, close}] series."""
    val = None
    for p in series:
        d = _to_date(p.get("date"))
        if d and d <= target:
            val = p.get("close")
        elif d and d > target:
            break
    return val


def market_cap_share(financials, prices_by_symbol, ticker_for, lookback_days: int = 30) -> list[dict]:
    """Each sector's share of the tracked universe's total market cap (USD-normalized),
    and how that share has shifted over ~`lookback_days`. 'Then' caps are approximated
    price-weighted (cap_then ≈ cap_now × close_then/close_now; shares ~constant), so a
    sector's share moves only as its constituents re-price. Honest label: share of
    *tracked market value*, not product market share. Pure — sorted by share desc."""
    from collections import defaultdict
    from datetime import timedelta

    now_by_sector: dict = defaultdict(float)
    then_by_sector: dict = defaultdict(float)
    for f in financials:
        ent = f.get("entity")
        tk = ticker_for(ent) if ent else None
        if not tk:
            continue
        cap = market_cap_usd(f.get("market_cap"), f.get("currency"))
        if not cap or cap <= 0:
            continue
        now_by_sector[tk.sector] += cap
        cap_then = cap                                  # default: flat (no price history)
        series = prices_by_symbol.get(tk.symbol) or []
        dates = [d for p in series if (d := _to_date(p.get("date")))]
        if dates:
            now_d = max(dates)
            now_close = _close_on_or_before(series, now_d)
            then_close = _close_on_or_before(series, now_d - timedelta(days=lookback_days))
            if now_close and then_close and float(now_close) > 0:
                cap_then = cap * (float(then_close) / float(now_close))
        then_by_sector[tk.sector] += cap_then

    total_now = sum(now_by_sector.values())
    total_then = sum(then_by_sector.values())
    if total_now <= 0:
        return []
    out = []
    for sec, cap in now_by_sector.items():
        share = round(100 * cap / total_now, 1)
        prev = round(100 * then_by_sector.get(sec, 0.0) / total_then, 1) if total_then else None
        out.append({"sector": sec, "market_cap": cap, "share": share,
                    "delta": round(share - prev, 1) if prev is not None else None})
    out.sort(key=lambda x: -x["share"])
    return out


def market_cap_donut(share_rows: list[dict]):
    """Donut of each sector's share of tracked market cap. None when empty."""
    if not share_rows:
        return None
    df = pd.DataFrame(share_rows)
    return alt.Chart(df).mark_arc(innerRadius=65).encode(
        theta=alt.Theta("share:Q", stack=True),
        color=alt.Color("sector:N", title=None, sort=list(df["sector"])),
        tooltip=[alt.Tooltip("sector:N", title="Sector"),
                 alt.Tooltip("share:Q", title="Share %", format=".1f"),
                 alt.Tooltip("delta:Q", title="Δ pp (30d)", format="+.1f")],
    ).properties(height=300)


def financial_context(stories, financials, prices_by_symbol, ticker_for,
                      window: int = 3, max_rd: int = 12) -> str:
    """Build a labelled COMPANY FINANCIALS block for an agent pack: R&D intensity
    (E1) for the companies in play, and measured market reactions (E2) to the
    *material* deals among `stories`, each tied to its [S#] id. Returns '' when
    there is nothing to add. Pure — `ticker_for(name)->Ticker|None` is injected.

    R&D intensity is a ratio and reactions are percentages, so this block is
    currency-agnostic — safe to hand an agent without unit confusion."""
    from analytics.mot_analyst import _is_capital_row

    fin_by_entity = {f["entity"]: f for f in financials if f.get("entity")}

    # R&D intensity for tracked companies that appear in today's stories (E1).
    in_play: list[dict] = []
    seen: set = set()
    for s in stories:
        for comp in (s.get("companies") or []):
            tk = ticker_for(str(comp))
            if tk and tk.entity in fin_by_entity and tk.entity not in seen:
                seen.add(tk.entity)
                in_play.append(fin_by_entity[tk.entity])
    rd_rows = sorted(
        (f for f in in_play if f.get("rd_intensity") is not None),
        key=lambda f: f["rd_intensity"], reverse=True,
    )[:max_rd]

    # Measured price reaction to each material deal, tied to its [S#] id (E2).
    reaction_lines: list[str] = []
    for i, s in enumerate(stories, 1):
        if str(s.get("business_impact") or "").lower() != "material":
            continue
        if not _is_capital_row(s):
            continue
        for comp in (s.get("companies") or []):
            tk = ticker_for(str(comp))
            if not tk:
                continue
            series = prices_by_symbol.get(tk.symbol)
            if not series:
                continue
            rx = event_reaction(s.get("published_at"), series, window=window)
            if rx:
                reaction_lines.append(
                    f"  - {tk.entity} {rx['pct']:+.1f}% over {rx['trading_days']} "
                    f"trading day(s) after [S{i}]"
                )
            break

    if not rd_rows and not reaction_lines:
        return ""

    out = ["=== COMPANY FINANCIALS (real figures — ground Capital signals [E1/E2] here) ==="]
    if rd_rows:
        out.append("R&D INTENSITY (R&D / revenue — funding the next S-curve [E1] vs harvesting):")
        for f in rd_rows:
            ri = f["rd_intensity"]
            out.append(f"  - {f['entity']}: {ri * 100:.1f}% ({investment_signal(ri)})")
    if reaction_lines:
        out.append("MARKET REACTION TO MATERIAL DEALS (did the stock re-price? a check on 'material' [E2]):")
        out += reaction_lines
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# Consultant-grade layer: valuation, investment intensity, landscape, deal flow,
# market validation, executive synthesis + KPIs, per-company scorecard. All pure.
# ══════════════════════════════════════════════════════════════════════════════
# Static FX → USD FALLBACK for the few non-USD listings. The write-time pipeline
# (financials_run) fetches live rates via finance.client.fx_rates_usd and passes
# them in; this map only catches a failed fetch, and every use logs a staleness
# warning citing FX_AS_OF so exhibits can footnote the rate source. Ratios like
# the valuation multiple / investment intensity are currency-agnostic and never
# use FX either way.
FX_AS_OF = "2026-07-02"  # date the fallback values below were last refreshed
_FX_TO_USD = {"USD": 1.0, "KRW": 0.000647, "CNY": 0.14, "EUR": 1.145, "JPY": 0.00621,
              "GBP": 1.33, "DKK": 0.1535, "CHF": 1.24, "TWD": 0.033, "HKD": 0.128}


def market_cap_usd(market_cap, currency, rates: dict | None = None) -> float | None:
    """Amount in USD. Prefers the live write-time `rates` ({CCY: →USD}); falls back
    to the static `_FX_TO_USD` map (dated FX_AS_OF) with a staleness warning. An
    unknown currency returns None with a warning — the company drops out of USD
    exhibits, but no longer silently. A missing currency is assumed USD (warned)."""
    try:
        m = float(market_cap)
    except (TypeError, ValueError):
        return None
    if not currency:
        logger.warning("market_cap_usd: missing currency — assuming USD")
    ccy = (currency or "USD").upper()
    if ccy == "USD":
        return m
    if rates and ccy in rates:
        return m * rates[ccy]
    fx = _FX_TO_USD.get(ccy)
    if fx is None:
        logger.warning("market_cap_usd: unknown currency %r — no FX rate, value dropped "
                       "from USD exhibits", currency)
        return None
    logger.warning("market_cap_usd: no live rate for %s — using static fallback %s "
                   "(as of %s; may be stale)", ccy, fx, FX_AS_OF)
    return m * fx


def valuation_multiple(market_cap, revenue) -> float | None:
    """Market cap / revenue (a crude P/S, not P/E). None if either is missing."""
    try:
        m = float(market_cap)
        r = float(revenue)
    except (TypeError, ValueError):
        return None
    return m / r if r > 0 else None


def investment_intensity(rd_expense, capex, revenue) -> float | None:
    """(R&D + capex) / revenue — total forward investment. R&D or capex alone is
    enough (some filers don't break out R&D). None if revenue missing or no spend."""
    try:
        rev = float(revenue)
    except (TypeError, ValueError):
        return None
    if rev <= 0:
        return None
    rd = float(rd_expense) if rd_expense is not None else 0.0
    cx = float(capex) if capex is not None else 0.0
    if rd == 0 and cx == 0:
        return None
    return (rd + cx) / rev


def landscape_points(financials, ticker_for) -> list[dict]:
    """Per-company points for the investment-landscape 2×2: investment intensity
    (x), valuation multiple (y), market cap (size), sector (colour). Only companies
    with both a multiple and an intensity. Pure."""
    pts = []
    for f in financials:
        mult = valuation_multiple(f.get("market_cap"), f.get("revenue"))
        inten = investment_intensity(f.get("rd_expense"), f.get("capex"), f.get("revenue"))
        if mult is None or mult <= 0 or inten is None:   # mult>0 required for the log axis
            continue
        tk = ticker_for(f.get("entity") or "")
        rev = float(f.get("revenue") or 0) or 1.0
        cap_usd = market_cap_usd(f.get("market_cap"), f.get("currency"))
        pts.append({
            "entity": f.get("entity"),
            "sector": tk.sector if tk else "Other",
            "intensity": round(inten * 100, 1),          # ratio — currency-agnostic
            "rd_pct": round((f.get("rd_intensity") or 0) * 100, 1),
            "capex_pct": round((float(f.get("capex") or 0) / rev) * 100, 1),
            "multiple": round(mult, 1),                  # ratio — currency-agnostic
            "market_cap": cap_usd if cap_usd is not None else 0.0,  # USD for sizing
        })
    return pts


def sector_rollup(financials, rows, ticker_for) -> list[dict]:
    """Portfolio view: per-sector company count, total market cap (USD), and median
    investment intensity / valuation multiple / R&D intensity, plus deal counts
    (commitment vs option) attributable to the sector's companies. Sorted by market
    cap. Pure."""
    from analytics.mot_analyst import capital_moves

    buckets: dict = {}
    for f in financials:
        tk = ticker_for(f.get("entity") or "")
        if not tk:
            continue
        b = buckets.setdefault(tk.sector, {"mult": [], "inten": [], "rd": [],
                                           "cap": 0.0, "companies": 0})
        b["companies"] += 1
        mult = valuation_multiple(f.get("market_cap"), f.get("revenue"))
        inten = investment_intensity(f.get("rd_expense"), f.get("capex"), f.get("revenue"))
        cap = market_cap_usd(f.get("market_cap"), f.get("currency"))
        if mult is not None:
            b["mult"].append(mult)
        if inten is not None:
            b["inten"].append(inten)
        if f.get("rd_intensity") is not None:
            b["rd"].append(f["rd_intensity"])
        if cap:
            b["cap"] += cap

    commit: dict = {}
    option: dict = {}
    for m in capital_moves(rows):
        secs = {tk.sector for c in (m.get("companies") or [])
                if (tk := ticker_for(str(c)))}
        for sec in secs:
            if m["kind"] == "commitment":
                commit[sec] = commit.get(sec, 0) + 1
            elif m["kind"] == "option":
                option[sec] = option.get(sec, 0) + 1

    out = []
    for sec, b in buckets.items():
        out.append({
            "sector": sec,
            "companies": b["companies"],
            "market_cap": b["cap"],
            "intensity": round(median(b["inten"]) * 100, 1) if b["inten"] else None,
            "multiple": round(median(b["mult"]), 1) if b["mult"] else None,
            "rd": round(median(b["rd"]) * 100, 1) if b["rd"] else None,
            "commitment": commit.get(sec, 0),
            "option": option.get(sec, 0),
        })
    out.sort(key=lambda x: x["market_cap"], reverse=True)
    return out


def deal_flow_timeline(rows, weeks: int = 8) -> list[dict]:
    """Weekly counts of capital moves split option vs commitment, for the last
    `weeks` weeks present in the data. Long-form [{week, kind, count}]. Pure —
    the reference 'now' is the latest dated move, so no clock is read."""
    from datetime import timedelta
    from collections import Counter
    from analytics.mot_analyst import capital_moves

    dated = []
    for m in capital_moves(rows):
        d = _to_date(m.get("published_at"))
        if d and m.get("kind") in ("option", "commitment"):
            dated.append((d, m["kind"]))
    if not dated:
        return []

    def week_start(d):
        return d - timedelta(days=d.weekday())

    ref = week_start(max(d for d, _ in dated))
    cutoff = ref - timedelta(weeks=weeks - 1)
    counts: Counter = Counter()
    for d, kind in dated:
        ws = week_start(d)
        if ws >= cutoff:
            counts[(ws.isoformat(), kind)] += 1

    out, w = [], cutoff
    while w <= ref:
        for kind in ("commitment", "option"):
            out.append({"week": w.isoformat(), "kind": kind,
                        "count": counts.get((w.isoformat(), kind), 0)})
        w += timedelta(weeks=1)
    return out


def capital_kpis(rows, financials, prices_by_symbol, ticker_for) -> dict:
    """Headline KPI tiles for the executive read. Pure."""
    from analytics.mot_analyst import capital_board

    board = capital_board(rows)
    c, o = board["counts"]["commitment"], board["counts"]["option"]
    rated = [f for f in financials if f.get("rd_intensity") is not None]
    top_rd = max(rated, key=lambda f: f["rd_intensity"], default=None)
    reactions = deal_reactions(rows, prices_by_symbol, ticker_for)
    biggest = max(reactions, key=lambda r: abs(r["pct"]), default=None)
    return {
        "deals": c + o,
        "commitment": c,
        "option": o,
        "ratio": f"{c}:{o}",
        "top_rd": ({"entity": top_rd["entity"], "pct": top_rd["rd_intensity"] * 100}
                   if top_rd else None),
        "biggest_reaction": ({"company": biggest["company"], "pct": biggest["pct"]}
                             if biggest else None),
        "total_market_cap": sum(
            (market_cap_usd(f.get("market_cap"), f.get("currency")) or 0.0)
            for f in financials),
    }


def capital_synthesis(rows, financials, prices_by_symbol, ticker_for) -> str:
    """Executive 'so what': posture + flag + lead investor + market validation, in
    a couple of sentences. Pure — deterministic, the agent narrative is separate."""
    from analytics.mot_analyst import capital_posture

    p = capital_posture(rows)
    k = capital_kpis(rows, financials, prices_by_symbol, ticker_for)
    # When there are too few clearly-typed moves to read a posture (the gated case),
    # don't assert a stance/over-extension verdict — say so plainly.
    if p["flag"] in ("none", "low-confidence"):
        parts = [f"Only **{p.get('n', 0)}** clearly-typed capital move(s) in the window — too "
                 "few to read a posture; the deals stand on their own."]
    else:
        stance = {"commitment": "committing capital in conviction bets",
                  "option": "hedging with small, staged options",
                  "balanced": "split between conviction bets and hedges"}.get(p["stance"], "quiet")
        mat = (p["maturity"] or "unclear").replace("-", " ")
        lead = f"Capital is **{stance}** into a **{mat}-stage** field"
        if p["flag"] == "over-extension":
            lead += " — an **over-extension** signal: big, irreversible bets ahead of proof."
        elif p["flag"] == "timid":
            lead += " — looking **timid / late** for a field whose design has largely settled."
        else:
            lead += "."
        parts = [lead]
    if k["top_rd"]:
        parts.append(f"{k['top_rd']['entity']} leads R&D intensity at "
                     f"{k['top_rd']['pct']:.0f}% of revenue.")
    if k["biggest_reaction"]:
        br = k["biggest_reaction"]
        # No causal claim ("rewarded/punished") — it's a raw, uncontrolled price move
        # over a short window, with no benchmark or beta. Say what happened in plain
        # English first; the caveat rides along instead of leading.
        verb = "rose" if br["pct"] > 0 else ("fell" if br["pct"] < 0 else "was flat at")
        parts.append(f"The sharpest market reaction around a deal: **{br['company']}** "
                     f"{verb} **{br['pct']:+.1f}%** within 3 trading days "
                     f"(raw move — not adjusted for the market or the stock's beta).")
    return " ".join(parts)


def company_scorecard(entity, financials, prices_by_symbol, rows, ticker_for) -> dict:
    """Per-company financial card for the drill-down: valuation, investment, cash,
    latest market reaction, E1 posture read. Pure."""
    fin = next((f for f in financials if f.get("entity") == entity), None) or {}
    tk = ticker_for(entity)
    rxs = [r for r in deal_reactions(rows, prices_by_symbol, ticker_for)
           if r["company"] == entity]
    return {
        "entity": entity,
        "symbol": tk.symbol if tk else None,
        "sector": tk.sector if tk else None,
        "market_cap": market_cap_usd(fin.get("market_cap"), fin.get("currency")),
        "revenue": fin.get("revenue"),
        "rd_intensity": fin.get("rd_intensity"),
        # basis of rd_expense when it isn't the plain yfinance statement row (e.g.
        # "curated-override (20-F FY2026)" for Toyota — finance.client.RD_OVERRIDES);
        # None/absent until migrations/2026-07-03_fx_asof.sql lands the column.
        "rd_basis": fin.get("rd_basis"),
        "multiple": valuation_multiple(fin.get("market_cap"), fin.get("revenue")),
        "investment_intensity": investment_intensity(
            fin.get("rd_expense"), fin.get("capex"), fin.get("revenue")),
        "cash": market_cap_usd(fin.get("cash"), fin.get("currency")),  # → USD for display
        "reaction": rxs[0] if rxs else None,
        "signal": investment_signal(fin.get("rd_intensity")),
    }


# ── chart builders (single/clean-layer Altair — safe to render headlessly) ──────
_SECTOR_RANGE = ["#2f80c4", "#cf6679", "#2f9e6d", "#e0a458", "#9b6dc4",
                 "#5bc0de", "#e07b39", "#7d8597", "#888"]


def landscape_chart(points: list[dict], label_top: int = 9):
    """Investment-landscape 2×2: investment intensity (x) vs valuation multiple
    (y, log), bubble = market cap, colour = sector, with median crosshairs. Only
    the largest few companies are labelled (the rest read via colour + tooltip).
    None when empty."""
    if not points:
        return None
    df = pd.DataFrame(points)
    base = alt.Chart(df)
    enc_x = alt.X("intensity:Q", title="Investment intensity — (R&D + capex) / revenue (%)",
                  scale=alt.Scale(zero=False, nice=True))
    enc_y = alt.Y("multiple:Q", title="Valuation — market cap / revenue (×, log)",
                  scale=alt.Scale(type="log"))
    bubbles = base.mark_circle(opacity=0.72).encode(
        x=enc_x, y=enc_y,
        size=alt.Size("market_cap:Q", scale=alt.Scale(range=[60, 1700]), legend=None),
        color=alt.Color("sector:N", title="Sector", scale=alt.Scale(range=_SECTOR_RANGE)),
        tooltip=[alt.Tooltip("entity:N", title="Company"),
                 alt.Tooltip("sector:N", title="Sector"),
                 alt.Tooltip("intensity:Q", title="Invest %"),
                 alt.Tooltip("multiple:Q", title="Rev multiple"),
                 alt.Tooltip("market_cap:Q", title="Market cap", format="$,.0f")],
    )
    # label only the biggest names — 29 labels overlap into an unreadable jumble
    top = df.nlargest(min(label_top, len(df)), "market_cap")
    labels = alt.Chart(top).mark_text(dy=-12, fontSize=10, color="#cfd4da").encode(
        x=enc_x, y=enc_y, text="entity:N")
    # median crosshairs — aggregate on the SAME field so the (log) scale is shared
    xrule = base.mark_rule(strokeDash=[4, 4], color="#888").encode(x="median(intensity):Q")
    yrule = base.mark_rule(strokeDash=[4, 4], color="#888").encode(y="median(multiple):Q")
    return (bubbles + xrule + yrule + labels).properties(height=440)


def sector_landscape_chart(rollup: list[dict]):
    """Sector-centroid scatter — the company 2×2 zoomed out: median investment
    intensity (x) vs median valuation multiple (y, log), bubble = total market cap,
    labelled by sector. None when empty."""
    data = [r for r in rollup
            if r.get("intensity") is not None and r.get("multiple") is not None]
    if not data:
        return None
    df = pd.DataFrame(data)
    base = alt.Chart(df)
    points = base.mark_circle(opacity=0.8).encode(
        x=alt.X("intensity:Q", title="Median investment intensity (%)",
                scale=alt.Scale(zero=False, nice=True)),
        y=alt.Y("multiple:Q", title="Median valuation (× revenue, log)",
                scale=alt.Scale(type="log")),
        size=alt.Size("market_cap:Q", scale=alt.Scale(range=[300, 2800]), legend=None),
        color=alt.Color("sector:N", title="Sector", scale=alt.Scale(range=_SECTOR_RANGE)),
        tooltip=[alt.Tooltip("sector:N", title="Sector"),
                 alt.Tooltip("companies:Q", title="Companies"),
                 alt.Tooltip("intensity:Q", title="Median invest %"),
                 alt.Tooltip("multiple:Q", title="Median multiple"),
                 alt.Tooltip("market_cap:Q", title="Total cap", format="$,.0f")],
    )
    labels = base.mark_text(dy=-15, fontSize=11, color="#cfd4da").encode(
        x="intensity:Q", y="multiple:Q", text="sector:N")
    return (points + labels).properties(height=380)


def investment_intensity_chart(points: list[dict], top: int = 15):
    """Stacked horizontal bars of R&D% + capex% of revenue per company (top by
    total), with a median-total reference rule. None when empty."""
    if not points:
        return None
    ranked = sorted(points, key=lambda p: p["intensity"], reverse=True)[:top]
    long = []
    for p in ranked:
        long.append({"entity": p["entity"], "component": "R&D", "pct": p["rd_pct"]})
        long.append({"entity": p["entity"], "component": "Capex", "pct": p["capex_pct"]})
    df = pd.DataFrame(long)
    med = float(pd.Series([p["intensity"] for p in ranked]).median())
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X("pct:Q", title="% of revenue", stack="zero"),
        y=alt.Y("entity:N", sort="-x", title=None),
        color=alt.Color("component:N", title=None,
                        scale=alt.Scale(domain=["R&D", "Capex"], range=["#2f9e6d", "#2f80c4"])),
        tooltip=[alt.Tooltip("entity:N", title="Company"),
                 alt.Tooltip("component:N", title="Type"),
                 alt.Tooltip("pct:Q", title="% rev")],
    )
    rule = alt.Chart(pd.DataFrame({"x": [med]})).mark_rule(
        strokeDash=[4, 4], color="#e0a458").encode(x="x:Q")
    return (bars + rule).properties(height=max(80, min(len(ranked) * 30 + 14, 460)))


def deal_flow_chart(timeline: list[dict]):
    """Stacked bars of weekly deal volume, option vs commitment. None when empty."""
    if not timeline:
        return None
    df = pd.DataFrame(timeline)
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("week:T", title="Week of"),
        y=alt.Y("count:Q", title="Capital moves", stack="zero"),
        color=alt.Color("kind:N", title=None,
                        scale=alt.Scale(domain=["commitment", "option"],
                                        range=["#cf6679", "#2f80c4"])),
        tooltip=[alt.Tooltip("week:T", title="Week"),
                 alt.Tooltip("kind:N", title="Type"),
                 alt.Tooltip("count:Q", title="Moves")],
    ).properties(height=240)


def reaction_chart(reactions: list[dict], top: int = 12):
    """Diverging bars of measured price moves after material deals, coloured by
    direction. None when empty."""
    if not reactions:
        return None
    data = [{"label": f"{r['company']} · {r.get('base_date', '')}",
             "pct": r["pct"], "direction": r["direction"]}
            for r in reactions[:top]]
    df = pd.DataFrame(data)
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("pct:Q", title="Price move ~3 trading days after the deal (%)"),
        y=alt.Y("label:N", sort="-x", title=None),
        color=alt.Color("direction:N", legend=None,
                        scale=alt.Scale(domain=["up", "flat", "down"],
                                        range=["#2f9e6d", "#888", "#cf6679"])),
        tooltip=[alt.Tooltip("label:N", title="Deal"),
                 alt.Tooltip("pct:Q", title="Move %"),
                 alt.Tooltip("direction:N", title="Direction")],
    ).properties(height=max(80, min(len(data) * 30 + 14, 420)))


def rd_intensity_chart(rows: list[dict]):
    """Horizontal bar of R&D intensity (%) for companies that have it. None if
    empty. rows: [{entity, rd_intensity}]."""
    data = [
        {"entity": r["entity"], "pct": round(float(r["rd_intensity"]) * 100, 1)}
        for r in rows
        if r.get("rd_intensity") is not None
    ]
    if not data:
        return None
    df = pd.DataFrame(data)
    return (
        alt.Chart(df)
        .mark_bar(color="#2f9e6d", cornerRadiusEnd=3)
        .encode(
            x=alt.X("pct:Q", title="R&D / revenue (%)"),
            y=alt.Y("entity:N", sort="-x", title=None),
            tooltip=[alt.Tooltip("entity:N", title="Company"),
                     alt.Tooltip("pct:Q", title="R&D %")],
        )
        .properties(height=max(70, min(len(df) * 30 + 12, 340)))
    )
