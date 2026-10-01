"""
Home — multi-feed news monitor.

Renders one tab per feed defined in `feeds.py` (EV, AI & Energy). Each tab reads
its own Supabase table (one table per feed) and renders title / summary / link.
The per-tab Refresh button calls the same runner used by the scheduled job.
"""

from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from config import Config
from feeds import FEEDS, Feed
from home_news.writer import HomeNewsWriter
from home_news_run import run_refresh

logger = logging.getLogger(__name__)

# Silence routine per-request chatter from HTTP libraries.
for _noisy in ("httpx", "httpcore", "hpack", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

st.set_page_config(
    page_title="Pharos",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Fail fast with a friendly message if core secrets are missing, rather than
# letting every Supabase call raise a cryptic error deeper in the app.
try:
    Config.validate()
except ValueError as e:
    st.error(
        f"⚠️ {e}. Set them in `.env` (or your deploy's secrets) and reload — "
        "see the README for the full env-var table."
    )
    st.stop()


@st.cache_resource
def _supabase():
    """One shared Supabase client for the whole app, reused across reruns."""
    from db import get_supabase
    return get_supabase()


@st.cache_resource
def _writer(table: str) -> HomeNewsWriter:
    return HomeNewsWriter(table=table, supabase_client=_supabase())


@st.cache_data(ttl=300, show_spinner=False)
def _feeds_last_fetched() -> str | None:
    """Most recent fetched_at across all feeds (cheap; one tiny query per feed)."""
    client = _supabase()
    latest: str | None = None
    for feed in FEEDS:
        try:
            resp = (
                client.table(feed.table)
                .select("fetched_at")
                .order("fetched_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            ts = rows[0].get("fetched_at") if rows else None
            if ts and (latest is None or ts > latest):
                latest = ts
        except Exception:
            continue
    return latest


# Sentiment badge used by the shared story card and the Entities view.
_SENT_BADGE = {"positive": "🟢 positive", "negative": "🔴 negative", "neutral": "⚪ neutral"}


def _src_name(path: str | None) -> str:
    """Readable source name from a corpus path (basename, no extension/dirs)."""
    if not path:
        return "source"
    base = str(path).replace("\\", "/").rstrip("/").split("/")[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def _clean_passage(text: str, limit: int = 700) -> str:
    """Collapse the corpus's ragged whitespace/line-breaks into a readable snippet."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return (t[:limit].rstrip() + "…") if len(t) > limit else t


def _render_provenance(row: dict) -> None:
    """The '🔍 Show your work / cite this' trail for one signal: source + copyable
    citation, per-field extraction provenance (agent / default / missing), the MOT
    lens trail, and a confidence read. Pure data from `analytics.provenance`."""
    from analytics.provenance import signal_provenance, PROVENANCE_LABEL

    pv = signal_provenance(row)
    src = pv["source"]
    # A popover, not an expander — story cards are often rendered *inside* an
    # expander (e.g. the lens browser), and Streamlit forbids nested expanders.
    with st.popover("🔍 Show your work / cite this"):
        head = f"**Source:** {html.escape(str(src['name']))}"
        if src.get("published_at"):
            head += f" · {html.escape(str(src['published_at']))}"
        if src.get("url"):
            # Percent-encode parens so a URL like ".../a(b)c" doesn't truncate the
            # markdown link at the first ')'. Browsers decode %28/%29 transparently.
            safe_url = src["url"].replace("(", "%28").replace(")", "%29")
            head += f" · [{html.escape(src['domain'] or 'link')} ↗]({safe_url})"
        st.markdown(head)

        if pv["has_provenance"]:
            st.caption(f"Extraction confidence: **{pv['confidence']}** — "
                       f"{pv['provided_count']}/{pv['field_count']} judgment fields came from the source.")
        else:
            st.caption("_Per-field provenance wasn't captured for this row (it predates the audit "
                       "trail) — showing field coverage instead._")

        for f in pv["fields"]:
            mark = "✅" if f["provided"] else ("🟡" if f["provenance"] in ("default", "present") else "⚪")
            st.markdown(
                f"- {mark} **{f['label']}:** {html.escape(str(f['value']))} "
                f"<span style='color:#8c959f;font-size:0.74rem'>· "
                f"{html.escape(PROVENANCE_LABEL.get(f['provenance'], f['provenance']))}</span>",
                unsafe_allow_html=True)

        lens = pv["lens"]
        if lens["classified"]:
            st.markdown(f"- 🔭 **MOT lens:** maturity `{lens['maturity']}` · "
                        f"adoption `{lens['adoption']}` · move `{lens['move']}`")
            if lens["rationale"]:
                st.caption(f"_{html.escape(str(lens['rationale']))}_")

        st.caption("Cite as:")
        st.code(pv["citation"], language=None)


def _story_card(
    row: dict,
    *,
    show_impact: bool = False,
    show_sentiment: bool = False,
    show_lens: bool = False,
    show_provenance: bool = False,
) -> None:
    """Render one story as a list item: source caption, title link, summary.

    Reads both the `_slim` shape (feed_icon/feed_label/also_in) and the raw
    all_recent shape (_feed_icon/_feed_label/_also_in) so it serves Pulse,
    Entities, and Framework. Flags add the materiality / sentiment badge or the
    MOT-lens line.
    """
    icon = row.get("feed_icon") or row.get("_feed_icon") or ""
    label = row.get("feed_label") or row.get("_feed_label") or ""
    bits = [f"{icon} {label}".strip()]
    if row.get("source_name"):
        bits.append(row["source_name"])
    if row.get("published_at"):
        bits.append(row["published_at"])
    also = row.get("also_in") or row.get("_also_in") or []
    if also:
        bits.append("also in " + ", ".join(also))
    if show_impact:
        impact = (row.get("business_impact") or "").lower()
        if impact == "material":
            bits.append("🔴 material")
        elif impact == "contextual":
            bits.append("🟡 contextual")
    if show_sentiment:
        badge = _SENT_BADGE.get((row.get("sentiment") or "").lower())
        if badge:
            bits.append(badge)

    st.markdown(f"**[{row.get('title', '(untitled)')}]({row.get('url', '#')})**")
    st.caption(" · ".join(b for b in bits if b))
    if row.get("summary"):
        st.markdown(row["summary"])
    if show_lens:
        st.markdown(
            f"maturity: `{row.get('maturity_stage')}` · adoption: `{row.get('adoption_stage')}` · "
            f"move: `{row.get('strategic_move')}`"
        )
        if row.get("lens_rationale"):
            st.caption(f"_{row['lens_rationale']}_")
    if show_provenance:
        _render_provenance(row)
    st.divider()


def _format_fetched(iso: str | None) -> str:
    if not iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        hours = int(delta.total_seconds() // 3600)
        if hours < 1:
            return "just now"
        if hours == 1:
            return "1 hour ago"
        if hours < 24:
            return f"{hours} hours ago"
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''} ago"
    except ValueError:
        return iso


# ISO alpha-2 → continent. Covers the countries that realistically appear in
# EV news; anything missing falls through to "Other".
_CONTINENT_BY_ISO: dict[str, str] = {
    # Europe
    **{c: "Europe" for c in [
        "GB", "IE", "FR", "DE", "ES", "PT", "IT", "NL", "BE", "LU", "CH", "AT",
        "DK", "SE", "NO", "FI", "IS", "PL", "CZ", "SK", "HU", "RO", "BG", "GR",
        "HR", "SI", "EE", "LV", "LT", "RS", "BA", "MK", "AL", "UA", "BY", "MD",
        "CY", "MT", "TR", "RU",
    ]},
    # Asia
    **{c: "Asia" for c in [
        "IN", "PK", "BD", "LK", "NP", "CN", "HK", "TW", "JP", "KR", "MN",
        "SG", "MY", "ID", "TH", "VN", "PH", "KH", "LA", "MM",
        "AE", "SA", "QA", "KW", "BH", "OM", "IL", "JO", "LB", "IQ", "IR", "SY",
        "KZ", "UZ", "AZ", "GE", "AM",
    ]},
    # Americas
    **{c: "Americas" for c in [
        "US", "CA", "MX",
        "BR", "AR", "CL", "CO", "PE", "EC", "VE", "UY", "PY", "BO",
        "GT", "HN", "SV", "NI", "CR", "PA", "CU", "DO", "PR", "JM", "TT",
    ]},
    # Africa
    **{c: "Africa" for c in [
        "ZA", "NG", "KE", "EG", "MA", "TN", "DZ", "ET", "GH", "TZ", "UG",
        "SN", "CI", "CM", "AO", "MZ", "ZW", "ZM", "RW", "BJ", "MU",
    ]},
    # Oceania
    **{c: "Oceania" for c in ["AU", "NZ", "FJ", "PG"]},
}

_CONTINENT_ORDER = ["All", "Europe", "Asia", "Americas", "Africa", "Oceania", "Global", "Other"]

# Tag-chip display order is per-feed; see `feeds.py` (Feed.tag_order).

# ISO alpha-2 → display name for chart labels. Covers the same set as
# _CONTINENT_BY_ISO; unknown codes fall back to the raw code.
_COUNTRY_NAMES: dict[str, str] = {
    "GB": "United Kingdom", "IE": "Ireland", "FR": "France", "DE": "Germany",
    "ES": "Spain", "PT": "Portugal", "IT": "Italy", "NL": "Netherlands",
    "BE": "Belgium", "LU": "Luxembourg", "CH": "Switzerland", "AT": "Austria",
    "DK": "Denmark", "SE": "Sweden", "NO": "Norway", "FI": "Finland",
    "IS": "Iceland", "PL": "Poland", "CZ": "Czechia", "SK": "Slovakia",
    "HU": "Hungary", "RO": "Romania", "BG": "Bulgaria", "GR": "Greece",
    "HR": "Croatia", "SI": "Slovenia", "EE": "Estonia", "LV": "Latvia",
    "LT": "Lithuania", "RS": "Serbia", "BA": "Bosnia and Herzegovina",
    "MK": "North Macedonia", "AL": "Albania", "UA": "Ukraine", "BY": "Belarus",
    "MD": "Moldova", "CY": "Cyprus", "MT": "Malta", "TR": "Türkiye", "RU": "Russia",
    "IN": "India", "PK": "Pakistan", "BD": "Bangladesh", "LK": "Sri Lanka",
    "NP": "Nepal", "CN": "China", "HK": "Hong Kong", "TW": "Taiwan",
    "JP": "Japan", "KR": "South Korea", "MN": "Mongolia", "SG": "Singapore",
    "MY": "Malaysia", "ID": "Indonesia", "TH": "Thailand", "VN": "Vietnam",
    "PH": "Philippines", "KH": "Cambodia", "LA": "Laos", "MM": "Myanmar",
    "AE": "United Arab Emirates", "SA": "Saudi Arabia", "QA": "Qatar",
    "KW": "Kuwait", "BH": "Bahrain", "OM": "Oman", "IL": "Israel",
    "JO": "Jordan", "LB": "Lebanon", "IQ": "Iraq", "IR": "Iran", "SY": "Syria",
    "KZ": "Kazakhstan", "UZ": "Uzbekistan", "AZ": "Azerbaijan",
    "GE": "Georgia", "AM": "Armenia",
    "US": "United States", "CA": "Canada", "MX": "Mexico", "BR": "Brazil",
    "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PE": "Peru",
    "EC": "Ecuador", "VE": "Venezuela", "UY": "Uruguay", "PY": "Paraguay",
    "BO": "Bolivia", "GT": "Guatemala", "HN": "Honduras", "SV": "El Salvador",
    "NI": "Nicaragua", "CR": "Costa Rica", "PA": "Panama", "CU": "Cuba",
    "DO": "Dominican Republic", "PR": "Puerto Rico", "JM": "Jamaica",
    "TT": "Trinidad and Tobago",
    "ZA": "South Africa", "NG": "Nigeria", "KE": "Kenya", "EG": "Egypt",
    "MA": "Morocco", "TN": "Tunisia", "DZ": "Algeria", "ET": "Ethiopia",
    "GH": "Ghana", "TZ": "Tanzania", "UG": "Uganda", "SN": "Senegal",
    "CI": "Côte d'Ivoire", "CM": "Cameroon", "AO": "Angola", "MZ": "Mozambique",
    "ZW": "Zimbabwe", "ZM": "Zambia", "RW": "Rwanda", "BJ": "Benin",
    "MU": "Mauritius",
    "AU": "Australia", "NZ": "New Zealand", "FJ": "Fiji", "PG": "Papua New Guinea",
}


def _country_name(code: str | None) -> str:
    if not code:
        return "Unknown"
    code = code.upper()
    if code == "GLOBAL":
        return "Global"
    return _COUNTRY_NAMES.get(code, code)


def _continent_for(code: str | None) -> str:
    if not code:
        return "Other"
    code = code.upper()
    if code == "GLOBAL":
        return "Global"
    return _CONTINENT_BY_ISO.get(code, "Other")


def _country_label(code: str | None) -> str:
    if not code:
        return ""
    if code.upper() == "GLOBAL":
        return "🌐 Global"
    try:
        # ISO alpha-2 → regional indicator emojis
        return "".join(chr(0x1F1E6 + ord(c.upper()) - ord("A")) for c in code if c.isalpha())
    except Exception:
        return code


def render_feed(feed: Feed) -> None:
    """Render one feed's refresh control, filter bar, and article grid.

    All widget / session-state keys are namespaced with the feed key so two
    feeds can render side-by-side in separate tabs without clashing.
    """
    writer = _writer(feed.table)
    k = feed.key  # namespace for per-tab widget / session-state keys

    # Per-feed manual refresh — runs just this one agent (the scheduled GitHub
    # Action and the header "Refresh all" cover the bulk path).
    _rcol_spacer, _rcol_btn = st.columns([4, 1])
    with _rcol_btn:
        do_refresh = st.button(
            "🔄 Refresh", key=f"refresh_{k}", width="stretch",
            disabled=not feed.api_key,
            help=None if feed.api_key else f"Set {feed.env_key} in .env to enable",
        )
    if do_refresh:
        prog = st.progress(0.0, text="Starting…")
        try:
            res = run_refresh(
                feed,
                status_callback=lambda msg, frac: prog.progress(
                    max(0.0, min(1.0, frac)), text=msg
                ),
            )
            prog.progress(1.0, text="Done")
            _feeds_last_fetched.clear()
            _pulse_snapshot.clear()
            _framework_rows.clear()
            st.success(
                f"{feed.label}: {res['items_parsed']} parsed · "
                f"{res['rows_upserted']} upserted · {res['rows_pruned']} pruned."
            )
            st.rerun()
        except Exception as e:
            st.error(f"Refresh failed: {e}")

    # Load and render.
    try:
        articles = writer.fetch_recent(limit=200)
    except Exception as e:
        st.error(f"Could not load news from Supabase: {e}")
        articles = []

    if not articles:
        st.info(
            f"No {feed.noun} in the feed yet. Click **Refresh** to fetch the first "
            f"batch — this requires the `{feed.table}` table to exist in "
            f"Supabase and `{feed.env_key}` to be set in `.env`."
        )
        return

    latest_fetch = max((a.get("fetched_at") or "" for a in articles), default=None)
    st.caption(f"Last updated {_format_fetched(latest_fetch)} · {len(articles)} items")

    # ── Filters: time range (right) + continent (left) ────────────────────────
    # Short labels keep all four chips on one row in a narrow column.
    _TIME_RANGES = {
        "1D": ("Day", 1),
        "1W": ("Week", 7),
        "1M": ("Month", 30),
        "1Y": ("Year", 365),
    }

    fcol_company, fcol_continent, fcol_filter, fcol_time = st.columns([1, 1, 1, 1])

    with fcol_time:
        time_key = st.segmented_control(
            "Time range",
            options=list(_TIME_RANGES.keys()),
            default="1M",
            label_visibility="collapsed",
            key=f"time_range_{k}",
        ) or "1M"

    time_label, time_days = _TIME_RANGES[time_key]
    cutoff = date.today() - timedelta(days=time_days)

    def _within_range(a: dict) -> bool:
        pub = a.get("published_at")
        if not pub:
            return True  # keep undated items rather than silently hiding them
        try:
            return date.fromisoformat(pub) >= cutoff
        except (TypeError, ValueError):
            return True

    articles = [a for a in articles if _within_range(a)]

    # Company filter — case-insensitive bucketing, ordered by count desc since
    # there's no canonical order. Counts reflect the time-filtered set.
    co_filter_counts: dict[str, int] = {}
    co_filter_display: dict[str, str] = {}
    for a in articles:
        for c in (a.get("companies") or []):
            name = str(c).strip()
            if not name:
                continue
            ckey = name.lower()
            co_filter_counts[ckey] = co_filter_counts.get(ckey, 0) + 1
            co_filter_display.setdefault(ckey, name)

    # Keep the user's selection sticky even when the current time/filter
    # combination has zero matches — the empty-state UI surfaces this clearly,
    # which is friendlier than silently resetting to "All".
    current_company = st.session_state.get(f"company_filter_{k}", "All")
    pretty_co_fallback = current_company.title()  # used if company gone from data

    if current_company == "All":
        company_button_label = "🏢 Company"
    else:
        pretty_co = co_filter_display.get(current_company, pretty_co_fallback)
        company_button_label = (
            f"🏢 {pretty_co if len(pretty_co) <= 14 else pretty_co[:13] + '…'}"
        )

    with fcol_company:
        with st.popover(company_button_label, width="stretch"):
            ordered_co = sorted(
                co_filter_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
            options = ["All"] + [c for c, _ in ordered_co]
            # Surface the active selection even if it isn't in the current
            # data, so the radio can render it (otherwise Streamlit warns and
            # silently flips it back to "All").
            if current_company != "All" and current_company not in options:
                options.append(current_company)

            if len(options) > 1:
                st.radio(
                    "Company",
                    options=options,
                    format_func=lambda c: (
                        "All" if c == "All"
                        else f"{co_filter_display.get(c, pretty_co_fallback)} "
                             f"({co_filter_counts.get(c, 0)})"
                    ),
                    key=f"company_filter_{k}",
                    label_visibility="collapsed",
                )
            else:
                st.caption("_No companies in the current view._")

    selected_company = st.session_state.get(f"company_filter_{k}", "All")

    if selected_company != "All":
        articles = [
            a for a in articles
            if selected_company in [
                str(c).strip().lower() for c in (a.get("companies") or [])
            ]
        ]

    # Continent filter — counts reflect the time+company filtered set so the
    # chips always show "what's actually available right now".
    counts: dict[str, int] = {}
    for a in articles:
        counts[_continent_for(a.get("country"))] = counts.get(_continent_for(a.get("country")), 0) + 1

    available = [c for c in _CONTINENT_ORDER if c == "All" or counts.get(c)]

    # Keep the user's continent selection sticky even when it has no matches
    # in the current time/company combination.
    current_continent = st.session_state.get(f"continent_filter_{k}", "All")
    if current_continent != "All" and current_continent not in available:
        available = available + [current_continent]

    continent_button_label = (
        "🌍 Continent" if current_continent == "All" else f"🌍 {current_continent}"
    )

    with fcol_continent:
        with st.popover(continent_button_label, width="stretch"):
            st.radio(
                "Continent",
                options=available,
                format_func=lambda c: (
                    c if c == "All"
                    else f"{c} ({counts.get(c, 0)})"
                ),
                key=f"continent_filter_{k}",
                label_visibility="collapsed",
            )

    selected = st.session_state.get(f"continent_filter_{k}", "All")

    if selected != "All":
        articles = [a for a in articles if _continent_for(a.get("country")) == selected]

    # Tag filter — popover button next to continent + time. Counts reflect the
    # continent+time filtered set so the choices show what's actually available.
    tag_counts: dict[str, int] = {}
    for a in articles:
        for t in (a.get("tags") or []):
            name = str(t).strip().lower()
            if name:
                tag_counts[name] = tag_counts.get(name, 0) + 1

    # Keep the user's tag selection sticky even when it has no matches in the
    # current time/company/continent combination.
    current_tag = st.session_state.get(f"tag_filter_{k}", "All")
    if current_tag == "All":
        button_label = "🏷️ Filter"
    else:
        pretty = current_tag.replace("-", " ").title()
        # Trim very long topic names so the button doesn't blow out the column.
        button_label = f"🏷️ {pretty if len(pretty) <= 18 else pretty[:17] + '…'}"

    with fcol_filter:
        with st.popover(button_label, width="stretch"):
            ordered = [t for t in feed.tag_order if t in tag_counts]
            # Surface any agent-invented tags after the known list.
            ordered += sorted(t for t in tag_counts if t not in feed.tag_order)
            tag_options = ["All"] + ordered
            # Keep the active selection visible even if it has no matches now.
            if current_tag != "All" and current_tag not in tag_options:
                tag_options.append(current_tag)

            if len(tag_options) > 1:
                st.radio(
                    "Topic",
                    options=tag_options,
                    format_func=lambda t: (
                        "All" if t == "All"
                        else f"{t.replace('-', ' ').title()} ({tag_counts.get(t, 0)})"
                    ),
                    key=f"tag_filter_{k}",
                    label_visibility="collapsed",
                )
            else:
                st.caption("_No topics available in the current view._")

    selected_tag = st.session_state.get(f"tag_filter_{k}", "All")

    if selected_tag != "All":
        articles = [
            a for a in articles
            if selected_tag in [
                str(t).strip().lower() for t in (a.get("tags") or [])
            ]
        ]

    if not articles:
        bits = [f"**{selected}**"]
        if selected_company != "All":
            bits.append(f"company **{co_filter_display.get(selected_company, selected_company)}**")
        if selected_tag != "All":
            bits.append(f"topic **{selected_tag.replace('-', ' ').title()}**")
        st.info(
            f"No articles in {' · '.join(bits)} for the past **{time_label.lower()}**."
        )
        # One-click escape hatch — sticky filters can otherwise pin the user in
        # the empty state until they clear each popover individually.
        if st.button("Clear all filters", key=f"clear_filters_{k}"):
            for _suffix in ("continent_filter", "company_filter", "tag_filter", "time_range"):
                st.session_state.pop(f"{_suffix}_{k}", None)
            st.rerun()
        return  # nothing to render — don't fall through to the empty grid loop

    # Optional: collapse near-duplicate coverage into events (corroboration view).
    if st.toggle("🗞️ Group duplicate coverage into events", key=f"events_{k}"):
        from analytics.events import cluster_events, multi_source_count
        events = cluster_events(articles)
        dupes = multi_source_count(events)
        st.caption(f"{len(events)} events from {len(articles)} stories · {dupes} multi-source.")
        for ev in events:
            rep = ev["rep"]
            st.markdown(f"#### [{rep.get('title', '(untitled)')}]({rep.get('url', '#')})")
            bits = []
            if ev["count"] > 1:
                bits.append(f"🗞️ {ev['count']} stories")
            if ev["sources"]:
                shown = ", ".join(ev["sources"][:5]) + (" …" if len(ev["sources"]) > 5 else "")
                bits.append(f"covered by {shown}")
            if rep.get("published_at"):
                bits.append(rep["published_at"])
            if bits:
                st.caption(" · ".join(bits))
            if rep.get("summary"):
                st.markdown(rep["summary"])
            if ev["count"] > 1:
                with st.expander(f"the {ev['count']} stories"):
                    for m in ev["members"]:
                        st.markdown(
                            f"- [{m.get('title', '')}]({m.get('url', '#')}) "
                            f"— {m.get('source_name') or '?'}"
                        )
            st.divider()
        return

    # 3-column grid, row-by-row so chronological order reads left-to-right.
    for row_start in range(0, len(articles), 3):
        cols = st.columns(3, gap="medium")
        for col, article in zip(cols, articles[row_start:row_start + 3]):
            with col:
                with st.container(border=True):
                    img_url = article.get("image_url")
                    if img_url:
                        # image_url is a Supabase Storage URL — verified at scrape time,
                        # served from same origin, so no hotlink / 404 surprises.
                        safe_url = html.escape(img_url, quote=True)
                        safe_alt = html.escape(article.get("title", ""), quote=True)
                        st.markdown(
                            f'<img src="{safe_url}" alt="{safe_alt}" loading="lazy" '
                            f'style="width:100%; height:140px; object-fit:cover; '
                            f'border-radius:8px; margin-bottom:0.5rem;" />',
                            unsafe_allow_html=True,
                        )

                    country = _country_label(article.get("country"))
                    source = article.get("source_name") or ""
                    published = article.get("published_at") or ""

                    header_bits = [b for b in (country, source, published) if b]
                    if header_bits:
                        st.caption(" · ".join(header_bits))

                    st.markdown(
                        f"#### [{article.get('title', '(untitled)')}]"
                        f"({article.get('url', '#')})"
                    )
                    st.markdown(article.get("summary", ""))

                    tags = article.get("tags") or []
                    if tags:
                        st.caption("Tags: " + ", ".join(f"`{t}`" for t in tags))


# ── Pulse: cross-feed overview ──────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _pulse_snapshot() -> dict:
    from analytics.aggregator import PulseAggregator
    return PulseAggregator(_supabase()).snapshot(days=7, top_n=12)


@st.cache_data(ttl=300, show_spinner=False)
def _feeds_health() -> list[dict]:
    from analytics.aggregator import PulseAggregator
    return PulseAggregator(_supabase()).feeds_health()


def _render_feed_health() -> None:
    """Per-feed operational status, behind an expander on Pulse."""
    with st.expander("🩺 Feed health"):
        try:
            health = _feeds_health()
        except Exception as e:
            st.caption(f"_Health check unavailable: {e}_")
            return
        import pandas as pd

        def _classified_pct(h: dict) -> str:
            if h["classified"] is None:
                return "n/a"  # lens columns not applied (see mot_lens_columns.sql)
            if not h["rows"]:
                return "0%"
            return f"{100 * h['classified'] // h['rows']}%"

        df = pd.DataFrame([
            {
                "Feed": f"{h['icon']} {h['label']}",
                "Key": "✓" if h["has_key"] else "✗ missing",
                "Rows": h["rows"],
                "Classified": _classified_pct(h),
                "Last fetched": _format_fetched(h["last_fetched"]),
                "Last rollup": h["last_rollup"] or "—",
            }
            for h in health
        ])
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption(
            "Key missing → set the feed's env var in `.env` / GitHub Secrets. "
            "Classified % is MOT-lens coverage (**n/a** → apply `database/schema/mot_lens_columns.sql`); "
            "last rollup feeds the Trends tab."
        )


def render_pulse() -> None:
    """The "what happened" overview — quick stats, feed health, top material
    stories. Rendered under the 🧭 Briefing tab beneath the Strategist read."""
    try:
        snap = _pulse_snapshot()
    except Exception as e:
        st.error(f"Could not load Pulse data from Supabase: {e}")
        return

    stats = snap.get("stats", {})
    sent = stats.get("sentiment", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Items (7d)", stats.get("total", 0))
    c2.metric("Material", stats.get("material", 0))
    c3.metric("Positive / negative", f"{sent.get('positive', 0)} / {sent.get('negative', 0)}")
    c4.metric("Feeds active", sum(1 for v in stats.get("per_feed", {}).values() if v))

    # Weighted prominence (material + reputable-source coverage counts more) so this
    # names the same leaders as the Trends Share-of-Voice default. Falls back to raw
    # counts for older snapshots cached before the weighted key existed.
    top_companies = stats.get("top_companies_weighted") or stats.get("top_companies", [])
    if top_companies:
        st.caption("Top players (by weighted coverage): "
                   + " · ".join(f"{name} ({n:g})" for name, n in top_companies[:6]))

    _render_feed_health()

    # ── Top material stories across all feeds ──
    st.markdown("### 🔝 Top stories across all feeds")
    top = snap.get("top_stories", [])
    if not top:
        st.info("No stories yet — click **Refresh all** to populate the feeds.")
        return
    for s in top:
        _story_card(s, show_impact=True)


# ── Strategist: theory-grounded read (replaces the Executive Brief) ─────────-

@st.cache_data(ttl=300, show_spinner=False)
def _latest_strategist(focus: str = "daily") -> dict | None:
    from analytics.strategist import Strategist
    return Strategist(_supabase()).latest(focus=focus)


@st.cache_data(ttl=300, show_spinner=False)
def _strategist_recent(focus: str = "daily") -> list[dict]:
    from analytics.strategist import Strategist
    return Strategist(_supabase()).recent(focus=focus, limit=2)


def _conf_chip(level: str) -> str:
    colors = {"high": "#1a7f37", "medium": "#9a6700", "low": "#6e7781"}
    lvl = (level or "").lower()
    return (
        f'<span style="background:{colors.get(lvl, "#6e7781")};color:#fff;'
        f'border-radius:10px;padding:1px 9px;font-size:0.72rem;font-weight:600;'
        f'white-space:nowrap;">● {html.escape(lvl or "—")}</span>'
    )


def _lens_badge(text: str) -> str:
    return (
        '<span style="background:#ddf4ff;color:#0550ae;border-radius:6px;'
        'padding:1px 9px;font-size:0.72rem;font-weight:600;white-space:nowrap;">'
        f'{html.escape(text or "signal")}</span>'
    )


# Which MOT Analyst exhibit illustrates each signal lens (a "see exhibit" pointer —
# Streamlit can't auto-switch tabs, so this is a labelled cross-reference).
_LENS_EXHIBIT = {
    "Discontinuity / new S-curve": "S-curve lifecycle map",
    "Dominant design locking in": "S-curve lifecycle map",
    "Early-niche traction": "Diffusion & chasm",
    "Chasm crossing": "Diffusion & chasm",
    "Standards battle": "Strategic-move matrix",
    "Entry timing": "Strategic-move matrix",
    "Appropriability": "Strategic-move matrix",
    "Platform play": "Strategic-move matrix",
    "Market-structure shift": "Momentum quadrant",
}
_CONF_COLORS = {"high": "#1a7f37", "medium": "#9a6700", "low": "#6e7781"}
_ACTION_COLORS = {
    "enter": "#1a7f37", "scale": "#1a7f37", "defend": "#0969da",
    "partner": "#8250df", "wait": "#6e7781", "exit": "#cf222e",
}
_HORIZON_LABEL = {"near": "near-term", "mid": "mid-term", "long": "long-term"}


def _action_chip(action: str) -> str:
    a = (action or "").lower()
    c = _ACTION_COLORS.get(a, "#6e7781")
    return (
        f'<span style="background:{c};color:#fff;border-radius:6px;padding:1px 9px;'
        'font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.03em;'
        f'white-space:nowrap;">{html.escape(a or "—")}</span>'
    )


def _impact_chip(impact: str) -> str:
    lvl = (impact or "").lower()
    dots = {"high": "●●●", "medium": "●●○", "low": "●○○"}.get(lvl, "○○○")
    return (
        f'<span style="color:#57606a;font-size:0.72rem;white-space:nowrap;" '
        f'title="impact: {html.escape(lvl or "—")}">{dots} impact</span>'
    )


def _signal_card_html(sig: dict) -> str:
    """One decisive-signal card as HTML — RAG left border by confidence; lens /
    impact / confidence chips; implication; value-capture; recommended action;
    falsifier; and a footer with sources, the 'see exhibit' pointer, and horizon."""
    lvl = (sig.get("confidence") or "").lower()
    accent = _CONF_COLORS.get(lvl, "#6e7781")
    lens = sig.get("lens") or "signal"
    srcs = sig.get("sources") or []
    src_ref = ("⟶ " + " · ".join(html.escape(s) for s in srcs)) if srcs else ""
    exhibit = _LENS_EXHIBIT.get(lens)
    ex_ref = f"↗ {html.escape(exhibit)}" if exhibit else ""
    hz = (sig.get("horizon") or "").lower()
    hz_ref = f"⏱ {html.escape(_HORIZON_LABEL.get(hz, hz))}" if hz else ""
    foot = " &nbsp;·&nbsp; ".join(x for x in (src_ref, ex_ref, hz_ref) if x)

    vc = sig.get("value_capture")
    vc_html = (
        '<div style="font-size:0.8rem;color:#6e4a00;background:#fff8e6;border-radius:4px;'
        f'padding:3px 8px;margin-top:0.45rem;">💰 <b>Value capture:</b> {html.escape(vc)}</div>'
    ) if vc else ""

    std = sig.get("standards") or {}
    std_html = ""
    if std.get("leader") or std.get("read"):
        basis = f" — leads on {html.escape(', '.join(std['basis']))}" if std.get("basis") else ""
        lead = html.escape(std.get("leader") or "")
        rd = f" {html.escape(std['read'])}" if std.get("read") else ""
        std_html = (
            '<div style="font-size:0.8rem;color:#0a3069;background:#ddf4ff;border-radius:4px;'
            f'padding:3px 8px;margin-top:0.4rem;">🏁 <b>Standards:</b> {lead}{basis}.{rd}</div>'
        )

    rat = sig.get("action_rationale") or ""
    action_html = (
        f'<div style="margin-top:0.5rem;">{_action_chip(sig.get("action"))} '
        f'<span style="font-size:0.82rem;color:#24292f;">{html.escape(rat)}</span></div>'
    ) if sig.get("action") else ""

    fals = sig.get("falsifier")
    fals_html = (
        '<div style="font-size:0.78rem;color:#57606a;margin-top:0.4rem;">'
        f'✕ <b>Falsifier:</b> {html.escape(fals)}</div>'
    ) if fals else ""

    return (
        f'<div style="border:1px solid #d0d7de;border-left:5px solid {accent};'
        'border-radius:8px;padding:0.7rem 0.9rem;margin-bottom:0.6rem;background:#fff;">'
        f'<div>{_lens_badge(lens)}&nbsp; {_impact_chip(sig.get("impact"))}&nbsp; {_conf_chip(lvl)}</div>'
        f'<div style="font-weight:700;font-size:1rem;margin:0.4rem 0 0.25rem;color:#1f2328;">'
        f'{html.escape(sig.get("title") or "")}</div>'
        f'<div style="font-size:0.9rem;color:#24292f;line-height:1.45;">'
        f'{html.escape(sig.get("implication") or "")}</div>'
        + vc_html + std_html + action_html + fals_html
        + (f'<div style="font-size:0.76rem;color:#57606a;margin-top:0.5rem;">{foot}</div>'
           if foot else "")
        + "</div>"
    )


def _render_structured_read(read: dict, stories: list[dict]) -> None:
    """Render the structured Strategist brief as a consultant deliverable:
    KPI strip → bottom line → decisive-signal cards → convergence → watchlist."""
    signals = read.get("signals") or []
    convergence = read.get("convergence") or []
    watch = read.get("watch") or []

    n_dev = len(stories)
    n_material = sum(1 for s in stories if (s.get("business_impact") or "").lower() == "material")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Developments", n_dev)
    k2.metric("Decisive signals", len(signals))
    k3.metric("Material", n_material)
    k4.metric("Confidence", (read.get("confidence") or "—").title())

    bl = read.get("bottom_line")
    if bl:
        st.markdown(
            '<div style="border-left:4px solid #0969da;background:#f6f8fa;'
            'padding:0.6rem 0.9rem;border-radius:4px;margin:0.4rem 0 0.8rem 0;">'
            '<div style="font-size:0.68rem;letter-spacing:0.09em;color:#57606a;">BOTTOM LINE</div>'
            f'<div style="font-size:1.05rem;font-weight:600;line-height:1.35;">{html.escape(bl)}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    # Portfolio decision board — the posture the per-signal actions imply.
    from analytics.strategist import portfolio_summary
    board = portfolio_summary(read)
    if board:
        chips = "&nbsp;&nbsp;".join(
            f'{_action_chip(b["action"])}<span style="font-size:0.8rem;color:#57606a;"> ×{b["count"]}</span>'
            for b in board
        )
        st.markdown(
            f'<div style="margin:0.1rem 0 0.7rem;"><span style="font-size:0.7rem;'
            f'letter-spacing:0.08em;color:#57606a;">PORTFOLIO POSTURE</span><br>{chips}</div>',
            unsafe_allow_html=True,
        )

    if signals:
        st.markdown("##### Decisive signals")
        for i in range(0, len(signals), 2):
            cols = st.columns(2, gap="medium")
            for col, sig in zip(cols, signals[i:i + 2]):
                with col:
                    st.markdown(_signal_card_html(sig), unsafe_allow_html=True)

    if convergence:
        st.markdown("##### Cross-domain convergence")
        for c in convergence:
            feeds = " + ".join(c.get("feeds") or [])
            tail = f" ({feeds})" if feeds else ""
            st.markdown(f"- **{c.get('theme', '')}**{tail} — {c.get('implication', '')}")

    scenarios = read.get("scenarios") or {}
    if any(scenarios.values()):
        st.markdown("##### Scenarios")
        cols = st.columns(3, gap="medium")
        for col, (k, label, color) in zip(
            cols, [("base", "Base", "#6e7781"), ("bull", "Bull", "#1a7f37"), ("bear", "Bear", "#cf222e")]
        ):
            with col:
                st.markdown(
                    f'<div style="border-top:3px solid {color};padding-top:0.3rem;">'
                    f'<b style="color:{color};">{label}</b><br>'
                    f'<span style="font-size:0.85rem;color:#24292f;">'
                    f'{html.escape(scenarios.get(k) or "—")}</span></div>',
                    unsafe_allow_html=True,
                )

    if watch:
        st.markdown("##### What to watch")
        _hz = {"near": "near-term", "mid": "mid-term"}
        for w in watch:
            hz = _hz.get((w.get("horizon") or "").lower())
            chip = f" `{hz}`" if hz else ""
            st.markdown(f"- **{w.get('item', '')}**{chip} — {w.get('why', '')}")


def _render_strategist_read(read, stories: list[dict]) -> None:
    """Render a cached read in whatever shape it's in — structured card deck
    preferred, markdown / legacy shapes as graceful fallbacks."""
    if not isinstance(read, dict):
        st.markdown(str(read))
        return
    if read.get("format") == "structured":
        _render_structured_read(read, stories)
    elif read.get("markdown"):
        st.markdown(read["markdown"])
    elif read.get("top_line") or read.get("headline"):
        st.markdown(f"**{read.get('top_line') or read.get('headline')}**")
    else:
        st.markdown(str(read))


def _render_brief_diff(prev: dict | None, read: dict) -> None:
    """Compact 'what changed since last briefing' panel."""
    if not prev or not isinstance(prev.get("strategic_read"), dict):
        return
    from analytics.strategist import diff_briefs
    d = diff_briefs(prev["strategic_read"], read)
    if not (d["new"] or d["dropped"] or d["changed"]):
        return
    with st.expander(f"🔄 What changed since {prev.get('as_of', 'last briefing')}", expanded=False):
        for t in d["new"]:
            st.markdown(f"- 🆕 **New signal:** {t}")
        for ch in d["changed"]:
            st.markdown(
                f"- 🔁 **{ch['title']}** — action {ch['from_action']}→**{ch['to_action']}**, "
                f"confidence {ch['from_confidence']}→**{ch['to_confidence']}**"
            )
        for t in d["dropped"]:
            st.markdown(f"- ✅ **Resolved / no longer decisive:** {t}")


def render_strategist() -> None:
    """The 🧭 Strategist: a cached, theory-grounded strategic read + its sources."""
    try:
        rows = _strategist_recent()
    except Exception:
        rows = []
    row = rows[0] if rows else None
    prev = rows[1] if len(rows) > 1 else None

    head, ctrl = st.columns([5, 1])
    with head:
        st.markdown("### 🧭 Strategist")
        st.caption("Decisive signals → recommended moves, read through MOT theory.")
    with ctrl:
        regen = st.button("Generate", key="strategist_gen", width="stretch")

    if regen:
        try:
            from analytics.strategist import Strategist
            with st.spinner("Reasoning over the latest material developments…"):
                Strategist(_supabase()).generate()
            _strategist_recent.clear()
            _latest_strategist.clear()
            st.rerun()
        except Exception as e:
            st.warning(f"Could not generate the strategic read: {e}")

    if not row or not row.get("strategic_read"):
        st.info(
            "No strategic read yet. Set `TOQAN_STRATEGIST` in `.env` (create the "
            "Strategist Toqan agent from `backend/Agents_prompt/Strategist_Agent.md`), then "
            "click **Generate** — or run `python backend/analytics_run.py`."
        )
        return

    read = row["strategic_read"]
    win = row.get("window_days")
    st.caption(
        f"As of {row.get('as_of', '?')}"
        + (f" · last {win} days" if win else "")
        + f" · focus: {row.get('focus', 'daily')}"
    )

    _render_brief_diff(prev, read)
    _render_strategist_read(read, row.get("stories") or [])

    from analytics.strategist import brief_to_markdown
    as_of, focus = row.get("as_of"), row.get("focus")
    fname = f"lodestar-briefing-{as_of or 'latest'}"
    dl_md, dl_pdf = st.columns(2)
    with dl_md:
        st.download_button(
            "⬇ Brief (.md)",
            data=brief_to_markdown(read, as_of=as_of, focus=focus),
            file_name=f"{fname}.md", mime="text/markdown", key="strat_dl_md", width="stretch",
        )
    with dl_pdf:
        try:
            from analytics.strategist import brief_to_pdf
            st.download_button(
                "⬇ Brief (.pdf)",
                data=brief_to_pdf(read, as_of=as_of, focus=focus),
                file_name=f"{fname}.pdf", mime="application/pdf", key="strat_dl_pdf", width="stretch",
            )
        except Exception:
            pass  # fpdf2 not installed — markdown download still available

    # The developments the read cited ([S#]).
    stories = row.get("stories") or []
    if stories:
        with st.expander(f"Developments it reasoned over ({len(stories)})"):
            for s in stories:
                label = s.get("label")
                if label:
                    st.markdown(f"**[{label}]**")
                _story_card(s, show_impact=True, show_lens=bool(s.get("maturity_stage")))

    # The MOT theory passages it cited ([T#]) — drop any non-substantive chunks
    # (index pages / reference lists) that a pre-filter brief may have stored.
    from vectordb.store import is_useful_chunk
    theory = [t for t in (row.get("theory") or []) if is_useful_chunk(t.get("chunk_text", ""))]
    if theory:
        with st.expander(f"MOT theory passages cited ({len(theory)})"):
            for t in theory:
                st.markdown(
                    f"**[{t.get('label')}] {_src_name(t.get('source_file'))}**  ·  "
                    f"relevance {float(t.get('similarity') or 0):.2f}"
                )
                st.markdown(f"> {_clean_passage(t.get('chunk_text', ''))}")
                st.divider()


# ── Trends dashboard (over the feed_daily_metrics rollup) ───────────────────

_TREND_RANGES = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365}


@st.cache_data(ttl=300, show_spinner=False)
def _trends_rows(feed_keys: tuple[str, ...], days: int) -> list[dict]:
    from analytics.trends import TrendsAggregator
    return TrendsAggregator(_supabase()).rows(list(feed_keys) or None, days)


def render_trends() -> None:
    """📈 Trends — what's moving: a headline read, KPI strip, a momentum
    leaderboard, compact volume/sentiment trends, and breakdowns in an expander."""
    import pandas as pd
    import altair as alt
    from analytics.trends import TrendsAggregator as TA

    ctrl_feed, ctrl_range = st.columns([3, 2])
    with ctrl_feed:
        options = ["All feeds"] + [f.label for f in FEEDS]
        choice = st.selectbox("Feed", options, key="trends_feed")
    with ctrl_range:
        rkey = st.segmented_control(
            "Range", list(_TREND_RANGES), default="90D", key="trends_range"
        ) or "90D"
    days = _TREND_RANGES[rkey]
    feed_keys = (tuple(f.key for f in FEEDS) if choice == "All feeds"
                 else tuple(f.key for f in FEEDS if f.label == choice))
    weighted = st.toggle(
        "⚖️ Weight by significance & source",
        value=True, key="trends_weighted",
        help="Rank by significance (material news counts 3× contextual; minor news much "
             "less) and source authority (reputable outlets count more) instead of raw "
             "article volume. Turn off for raw mention counts.",
    )

    rows = _trends_rows(feed_keys, days)
    if not rows:
        st.info(
            "No rollup data yet. Click **Refresh all** (or run `python backend/analytics_run.py`) "
            "to build `feed_daily_metrics` — long ranges fill in as it accumulates."
        )
        return

    vol = TA.daily_volume(rows)
    sent = TA.daily_sentiment(rows)
    mom = TA.momentum(rows, days)
    pos = sum(s["positive"] for s in sent)
    neg = sum(s["negative"] for s in sent)

    # Headline read + KPI strip
    st.markdown(TA.headline(rows, days))
    # Pick the momentum leader from feeds with a real base — a 0→1 swing reads +100%
    # but isn't momentum, so thin feeds are excluded from the headline KPI.
    solid_mom = [m for m in mom if not m.get("thin")]
    leader = max(solid_mom, key=lambda m: m["pct"]) if solid_mom else None
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Articles", sum(v["count"] for v in vol))
    k2.metric("Net sentiment", pos - neg, help="positive − negative across the window")
    k3.metric("Positive / negative", f"{pos} / {neg}")
    k4.metric("Top momentum", leader["feed"] if leader else "—",
              delta=f"{leader['pct']:+.0f}%" if leader else None,
              help="Fastest-rising feed (recent vs prior half of the window). Feeds with "
                   "fewer than 5 articles in the prior half are excluded — the base is "
                   "too thin to call momentum.")

    # Momentum leaderboard — the centerpiece (cross-feed only)
    if choice == "All feeds" and len(mom) > 1:
        st.markdown("#### 🚀 Momentum — which feeds are rising")
        mdf = pd.DataFrame(mom)
        mdf["dir"] = mdf["pct"].apply(lambda p: "rising" if p >= 0 else "cooling")
        st.altair_chart(
            alt.Chart(mdf).mark_bar().encode(
                x=alt.X("pct:Q", title="% change vs prior half of range"),
                y=alt.Y("feed:N", sort="-x", title=None),
                color=alt.Color("dir:N",
                                scale=alt.Scale(domain=["rising", "cooling"], range=["#1a7f37", "#cf6679"]),
                                legend=None),
                tooltip=[alt.Tooltip("feed:N"), alt.Tooltip("recent:Q"), alt.Tooltip("prior:Q"),
                         alt.Tooltip("pct:Q", format="+.0f", title="% change")],
            ).properties(height=max(150, 30 * len(mom))),
            width="stretch",
        )

    # Share of voice — who's dominating the conversation, and how it's shifting.
    # half_split keeps the recent/prior halves equal-length and in lockstep with
    # momentum's split (the old local days//2 derivation was off by one).
    mid = TA.half_split(days)[1]
    sov = TA.voice_share(rows, mid, top=8, weighted=weighted)
    share_noun = "weighted mentions" if weighted else "mentions"
    cnt_fmt = ".1f" if weighted else ".0f"
    if sov["slices"]:
        st.markdown("#### 📊 Share of voice — who's dominating the conversation")
        # Ranked bars of the NAMED leaders only — a donut buries them under one giant
        # 'Others' wedge (the long tail). The tail goes to the caption instead.
        named = sorted((s for s in sov["slices"] if s["name"] != "Others"),
                       key=lambda s: s["share"], reverse=True)
        if named:
            bdf = pd.DataFrame(named)
            bdf["dir"] = bdf["delta"].map(
                lambda d: "rising" if (d or 0) > 0 else ("falling" if (d or 0) < 0 else "flat / new"))
            bdf["label"] = [f"{s['share']:.1f}%" + (f"  {s['delta']:+.1f}pp" if s["delta"] is not None else "")
                            for s in named]
            # Explicit category order (named is already share-desc) — robust across the
            # layered bars+text, where sort="-x" silently falls back to alphabetical.
            enc_y = alt.Y("name:N", sort=[s["name"] for s in named], title=None)
            bars = alt.Chart(bdf).mark_bar(cornerRadiusEnd=3).encode(
                x=alt.X("share:Q", title=f"share of recent {share_noun} (%)"),
                y=enc_y,
                color=alt.Color("dir:N",
                                scale=alt.Scale(domain=["rising", "flat / new", "falling"],
                                                range=["#74c476", "#9aa7b4", "#e5736a"]),
                                legend=alt.Legend(title="vs prior half", orient="bottom")),
                tooltip=[alt.Tooltip("name:N", title="Player"),
                         alt.Tooltip("share:Q", title="Share %", format=".1f"),
                         alt.Tooltip("count:Q", title=share_noun.capitalize(), format=cnt_fmt),
                         alt.Tooltip("delta:Q", title="Δ pp vs prior half", format="+.1f")],
            )
            text = alt.Chart(bdf).mark_text(align="left", dx=4, fontSize=11, color="#24292f").encode(
                x="share:Q", y=enc_y, text="label:N")
            st.altair_chart((bars + text).properties(height=max(180, 34 * len(named))), width="stretch")

        movers = [s for s in named if s.get("delta") is not None]
        risen = max(movers, key=lambda s: s["delta"], default=None)
        fallen = min(movers, key=lambda s: s["delta"], default=None)
        bits = []
        if risen and risen["delta"] > 0:
            bits.append(f"📈 **{risen['name']}** {risen['delta']:+.1f}pp")
        if fallen and fallen["delta"] < 0:
            bits.append(f"📉 **{fallen['name']}** {fallen['delta']:+.1f}pp")
        others = next((s for s in sov["slices"] if s["name"] == "Others"), None)
        tail = (f" · the remaining **{others['share']:.0f}%** is the long tail across "
                f"{max(0, sov.get('n_entities', 0) - len(named))} more entities") if others else ""
        weight_note = (" Weighted by significance & source — material news and reputable "
                       "outlets count more than raw volume." if weighted else "")
        st.caption(f"Top {len(named)} of {sov.get('n_entities', len(named))} entities by share of recent "
                   f"{share_noun}{tail}."
                   + (("  " + " · ".join(bits) + " vs the prior half.") if bits else "")
                   + weight_note)

    # Trends over time
    cL, cR = st.columns(2)
    with cL:
        st.markdown("#### Volume over time")
        vdf = pd.DataFrame(vol)
        if not vdf.empty:
            vdf["date"] = pd.to_datetime(vdf["date"])
            if choice == "All feeds":
                st.area_chart(vdf.pivot_table(index="date", columns="feed", values="count",
                                              aggfunc="sum").fillna(0))
            else:
                st.area_chart(vdf.groupby("date")["count"].sum())
    with cR:
        st.markdown("#### Sentiment over time")
        sdf = pd.DataFrame(sent)
        if not sdf.empty:
            sdf["date"] = pd.to_datetime(sdf["date"])
            st.line_chart(sdf.set_index("date")[["positive", "negative", "neutral"]])

    # Breakdowns — reference detail, tucked away
    with st.expander("Breakdowns — companies · countries · business impact · scope · topics"):
        def _bar(col, title, field, top=12):
            data = TA.sum_marginal(rows, field, top=top)
            col.markdown(f"**{title}**")
            if data:
                col.bar_chart(pd.DataFrame(data, columns=[field, "count"]).set_index(field))
            else:
                col.caption("_no data_")
        a, b = st.columns(2)
        _bar(a, "Top companies (raw mentions)", "by_company")
        _bar(b, "Top countries", "by_country")
        c, d = st.columns(2)
        _bar(c, "Business-impact mix", "by_impact")
        _bar(d, "Scope mix", "by_scope")
        _bar(st, "Top topics (tags)", "by_tag", top=15)


# ── Entity tracking (one company across all feeds) ──────────────────────────

_ENTITY_RANGES = {"30D": 30, "90D": 90, "180D": 180}


@st.cache_data(ttl=300, show_spinner=False)
def _entity_universe(days: int) -> list[tuple[str, int]]:
    from analytics.entity_tracker import EntityTracker
    return EntityTracker(_supabase()).universe(days=days, top=60)


@st.cache_data(ttl=300, show_spinner=False)
def _entity_profile(entity: str, days: int) -> dict:
    from analytics.entity_tracker import EntityTracker
    return EntityTracker(_supabase()).profile(entity, days=days)


def render_entities() -> None:
    """🔍 Entity dossier: a one-line read, KPI strip, presence + trajectory,
    co-mentioned players (its ecosystem), then the recent stories."""
    import pandas as pd
    from analytics.entity_tracker import co_mentions, entity_read

    crange, cpick = st.columns([1, 3])
    with crange:
        rkey = st.segmented_control(
            "Range", list(_ENTITY_RANGES), default="90D", key="ent_range"
        ) or "90D"
    days = _ENTITY_RANGES[rkey]

    universe = _entity_universe(days)
    if not universe:
        st.info(
            "No entity data yet. Click **Refresh all** to populate the feeds (and the "
            "rollup), then pick a company here."
        )
        return

    name_by_option = {f"{name}  ({n})": name for name, n in universe}
    with cpick:
        sel = st.selectbox("Entity", list(name_by_option), key="ent_pick")
    entity = name_by_option[sel]

    prof = _entity_profile(entity, days)
    fc = prof["feeds_count"]
    sent = prof["sentiment"]

    hcol, tcol = st.columns([5, 1])
    hcol.markdown(f"### {entity}")
    if tcol.button("🔔 Track", key="ent_track", width="stretch"):
        from analytics.watchlist import Watchlist
        Watchlist(_supabase()).add("entity", entity)
        _watchlist_alerts.clear()
        st.toast(f"Tracking {entity} for alerts.")
    st.markdown(entity_read(entity, prof))

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Prominence (wtd)", f"{prof.get('weighted', 0):.1f}",
              help=f"Significance- & source-weighted mentions over the range — the same "
                   f"measure that ranks the picker. {prof['total']} raw mentions in the live window.")
    k2.metric("Feeds", fc)
    k3.metric("Positive / negative", f"{sent.get('positive', 0)} / {sent.get('negative', 0)}")
    k4.metric("Reach", "🔗 cross-domain" if fc >= 2 else "single feed")

    cL, cR = st.columns(2)
    with cL:
        st.markdown("#### Where it shows up")
        by_feed = prof["by_feed"]
        if by_feed:
            st.bar_chart(pd.DataFrame(list(by_feed.items()), columns=["feed", "mentions"]).set_index("feed"))
        else:
            st.caption("_No recent mentions in the live window._")
    with cR:
        st.markdown("#### Mentions over time")
        series = prof["series"]
        if series:
            df = pd.DataFrame(series)
            df["date"] = pd.to_datetime(df["date"])
            st.area_chart(df.pivot_table(index="date", columns="feed", values="count", aggfunc="sum").fillna(0))
        else:
            st.caption("_No rollup history yet — fills in as the rollup accumulates._")

    # Co-mention chord — the entity's ego-network: who it's named with AND how
    # those players interconnect (ribbons), coloured by their dominant feed.
    st.markdown("#### 🕸️ Co-mention network")
    st.caption(
        f"Players named alongside **{entity}** — and how they interconnect. Colour = "
        "dominant feed; ribbons spanning colours are cross-domain links."
    )
    if not _comention_chord(prof["stories"], top=12, height=520):
        # Fall back to a simple bar when there aren't enough co-occurring players.
        co = co_mentions(prof["stories"], entity)
        if co:
            st.bar_chart(pd.DataFrame(co, columns=["player", "co-mentions"]).set_index("player"))
        else:
            st.caption("_No co-mentioned players in the recent window._")

    st.markdown("#### Recent stories")
    stories = prof["stories"]
    if not stories:
        st.caption("_No recent stories mentioning this entity in the live window._")
    for s in stories:
        _story_card(s, show_sentiment=True)


# ── Framework: MOT-lens view ────────────────────────────────────────────────

_LENS_FIELDS = {
    "maturity_stage": "Maturity stage — Technology Dynamics (S-curve)",
    "adoption_stage": "Adoption stage — diffusion of innovation",
    "strategic_move": "Strategic move — tech strategy (Schilling)",
}
_LENS_SKIP = {"maturity_stage": "n/a", "adoption_stage": "n/a", "strategic_move": "none"}


@st.cache_data(ttl=300, show_spinner=False)
def _framework_rows() -> list[dict]:
    from analytics.aggregator import PulseAggregator
    return PulseAggregator(_supabase()).all_recent(days=30)


@st.cache_data(ttl=900, show_spinner=False)
def _company_financials() -> list[dict]:
    """Fundamentals snapshots from financials_run.py (empty list if never run)."""
    try:
        return _supabase().table("company_financials").select("*").execute().data or []
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def _stock_prices() -> dict:
    """{symbol: [{date, close}] ascending} from stock_prices (empty if never run).
    Paginates past Supabase's 1000-row default cap — the full series is ~31×120 rows."""
    out: dict = {}
    try:
        sb = _supabase()
        start = 0
        while True:
            chunk = (sb.table("stock_prices").select("symbol,day,close")
                     .order("symbol").order("day").range(start, start + 999).execute().data or [])
            for r in chunk:
                out.setdefault(r["symbol"], []).append({"date": r["day"], "close": r["close"]})
            if len(chunk) < 1000:
                break
            start += 1000
    except Exception:
        return {}
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _tech_transitions() -> list[dict]:
    from analytics.tech_layer import TechAnalyst
    return TechAnalyst(_supabase()).transitions()


def _render_tech_scurve(plc: list[dict]) -> None:
    """Lead exhibit: tracked technologies on the S-curve (the MOT unit of analysis)."""
    from analytics import mot_analyst as ma
    from analytics.tech_layer import display_stage
    import pandas as pd

    st.markdown("#### 🧬 Technologies on the S-curve")
    st.caption(
        "Articles rolled up to tracked technologies and placed by the **centroid** of their "
        "lifecycle-stage spread (policy/energy `n/a` stories excluded) — so a contested topic "
        "sits at the *centre* of its spread, not on whichever stage won a thin plurality. "
        "**Faded dots** are contested (no majority stage). Dot size = on-curve coverage; colour = domain."
    )
    chart = ma.tech_scurve_chart(plc)
    if chart is None:
        st.caption("_No tracked technology has enough classified coverage in this window yet._")
        return
    st.altair_chart(chart, width="stretch")
    st.caption(ma.interpret_tech(plc))

    # Companion lens: market uptake (Rogers/Moore) underneath the maturity S-curve.
    ad_chart = ma.adoption_curve_chart(plc)
    if ad_chart is not None:
        st.markdown("##### 📈 Innovation-adoption lifecycle — market uptake (with the chasm)")
        st.caption(
            "The same technologies on the **diffusion** curve (Rogers): innovators → early "
            "adopters → ‖ the chasm ‖ → early/late majority → laggards. The S-curve above tracks "
            "the *technology's* maturity; this tracks *market adoption* — a tech can be maturing "
            "fast yet stuck pre-chasm. Faded = contested; dot size = on-curve coverage."
        )
        st.altair_chart(ad_chart, width="stretch")

    with st.expander(f"Placement table ({len(plc)} technologies)"):
        df = pd.DataFrame([{
            "Technology": p["label"], "Domain": p["domain"],
            "Stage": display_stage(p) or "—",
            "Confidence": "mixed" if p.get("mixed") else "clear",
            "Adoption": display_stage(p, "adoption") or "—", "Move": p["move"] or "—",
            "On-curve": p.get("stage_articles", p["articles"]),
            "n/a": p["articles"] - p.get("stage_articles", p["articles"]),
            "Players": p["entrants"],
        } for p in plc])
        st.dataframe(df, hide_index=True, width="stretch")


def _render_transitions() -> None:
    """The decisive events: technologies that changed lifecycle stage."""
    st.markdown("##### 🔀 Stage transitions — the decisive events")
    st.caption(
        "A technology changing lifecycle stage between snapshots. **Forward moves shown; "
        "backward 'regressions' are collapsed below.** Maturity and adoption are near-monotonic, "
        "so a flag means *don't act on it yet*: ⏳ **pending** (only one snapshot old — not yet "
        "confirmed), ⚠️ **contested** (no majority stage behind the new placement)."
    )
    try:
        trans = _tech_transitions()
    except Exception:
        trans = []
    if not trans:
        st.caption(
            "_No transitions yet — they appear once the daily snapshot has ≥2 days of history "
            "(apply `technology_stage_history.sql` and run `analytics_run.py` over time)._"
        )
        return

    def _conf(t: dict) -> str:
        if t.get("contested"):
            return " · ⚠️ _contested (no majority stage — watch, not decisive)_"
        if t.get("confirmed") is False:
            return " · ⏳ _pending (one snapshot old — not yet confirmed)_"
        ms = t.get("modal_share")
        return f" · {ms:.0%} of articles agree" if isinstance(ms, (int, float)) else ""

    def _line(t: dict) -> str:
        return (f"- **{t['label']}** — {t['dimension']} **{t['from']} → {t['to']}** "
                f"_(as of {t.get('as_of', '?')})_")

    # The list is already sorted forward-first, backward last. Split on direction:
    # forward moves are the real signal (shown); backward moves are near-impossible on
    # these monotonic axes (collapsed for audit, not headlined).
    forward = [t for t in trans if not t.get("backward")]
    backward = [t for t in trans if t.get("backward")]

    if forward:
        for t in forward[:12]:
            st.markdown(_line(t) + _conf(t))
    else:
        st.caption("_No trustworthy (forward) moves this snapshot._")

    if backward:
        with st.expander(f"↩️ {len(backward)} suspect move(s) — backward, likely re-estimation noise"):
            st.caption(
                "Maturity and adoption don't run backward in reality (adoption is cumulative — "
                "you don't un-cross the chasm), so these are almost certainly re-estimation between "
                "snapshots, surfaced for audit, not action. A whole cohort regressing at once usually "
                "means the prior snapshot was an outlier or the history is still thin."
            )
            for t in backward:
                st.markdown(_line(t))


def _render_curves() -> None:
    """Measured performance + adoption curves (seeded, illustrative)."""
    from analytics import mot_analyst as ma
    from benchmarks import BENCHMARKS, ADOPTION_BENCHMARKS
    from technologies import TECH_BY_KEY

    def _picker(title: str, hint: str, data: dict, key: str) -> None:
        keys = [k for k in data if k in TECH_BY_KEY]
        if not keys:
            return
        st.markdown(f"##### {title}")
        st.caption(hint)
        labels = {TECH_BY_KEY[k].label: k for k in keys}
        pick = st.selectbox("Technology", list(labels), key=key, label_visibility="collapsed")
        spec = data[labels[pick]]
        chart = ma.benchmark_chart(spec)
        if chart is not None:
            st.altair_chart(chart, width="stretch")
            arrow = "lower is better ↓" if spec.get("lower_is_better") else "higher is better ↑"
            st.caption(f"{spec.get('metric')} ({spec.get('unit')}) — {arrow} · {spec.get('note', '')}")

    cperf, cadopt = st.columns(2)
    with cperf:
        _picker("📉 Performance curves",
                "Performance vs. time — the *actual* S-curve. _Illustrative seed data._",
                BENCHMARKS, "bench_pick")
    with cadopt:
        _picker("📈 Adoption curves",
                "Diffusion / penetration over time — quantifies the chasm call. _Illustrative._",
                ADOPTION_BENCHMARKS, "adopt_pick")


def _render_ferment(plc: list[dict]) -> None:
    """Design convergence — ferment (many players) → dominant design (few)."""
    from analytics import mot_analyst as ma
    st.markdown("##### ⚗️ Design convergence (ferment → dominant design)")
    regimed = ma.ferment_regime(plc)
    fchart = ma.ferment_chart(regimed)
    if fchart is not None:
        st.altair_chart(fchart, width="stretch")
        st.caption(ma.interpret_ferment(regimed))
    else:
        st.caption("_Needs classified technologies in the window._")


def _chart_block(title: str, chart, caption: str, empty_hint: str) -> None:
    """Render one analyst chart: heading, the Altair chart (or a hint), interpretation."""
    st.markdown(f"#### {title}")
    if chart is not None:
        st.altair_chart(chart, width="stretch")
        if caption:
            st.caption(caption)
    else:
        st.caption(empty_hint)


def _render_scorecard(classified: list[dict]) -> None:
    """The consultant deliverable: a templated 7-questions readout for a chosen
    entity, plus an on-demand agent-written narrative (the Strategist, focused)."""
    from analytics import mot_analyst as ma

    st.markdown("#### 🎯 MOT scorecard")
    universe = ma.entity_universe(classified)
    if not universe:
        st.caption("_No named entities in the classified set yet._")
        return
    ent = st.selectbox("Entity / sector", universe, key="ma_scorecard_entity")
    card = ma.scorecard(classified, ent)
    st.caption(
        f"**{card['entity']}** · {card['mentions']} classified mention(s) across "
        f"{len(card['feeds'])} feed(s): {', '.join(card['feeds']) or '—'}"
    )
    for qa in card["questions"]:
        st.markdown(f"- **{qa['q']}** — {qa['a']}")

    # Agent-written narrative (focused Strategist read), cached per entity.
    if st.button(f"🧭 Analyst's read on {ent}", key="ma_scorecard_gen"):
        try:
            from analytics.strategist import Strategist
            with st.spinner("Asking the Strategist…"):
                Strategist(_supabase()).generate(focus=ent)
            _latest_strategist.clear()
        except Exception as e:
            st.warning(f"Strategist read unavailable: {e}")
    try:
        read = _latest_strategist(ent)
    except Exception:
        read = None
    if read and read.get("strategic_read"):
        with st.expander(f"🧭 Strategist's read on {ent} (as of {read.get('as_of', '?')})"):
            _render_strategist_read(read["strategic_read"], read.get("stories") or [])


_CHORD_PALETTE = ["#4e79a7", "#59a14f", "#e15759", "#76b7b2", "#f28e2b",
                  "#b07aa1", "#edc948", "#9c755f", "#bab0ac"]


def _comention_chord(rows: list[dict], top: int = 14, height: int = 600) -> bool:
    """Render a co-mention chord from `rows`; return False (drawing nothing) if
    there aren't enough co-occurring players (<3) so the caller can fall back."""
    from analytics.entity_tracker import co_occurrence_matrix, chord_html

    data = co_occurrence_matrix(rows, top=top)
    if len(data["labels"]) < 3:
        return False
    domains_present = list(dict.fromkeys(data["domains"]))
    colors = {dm: _CHORD_PALETTE[i % len(_CHORD_PALETTE)] for i, dm in enumerate(domains_present)}
    st.iframe(chord_html(data, colors), height=height)
    return True


def _render_convergence_radar(rows: list[dict]) -> None:
    """MOT Analyst: name the colliding domains + who sits at the seam (the A4
    multi-technology signal made explicit, not just drawn as chord ribbons)."""
    from analytics.entity_tracker import domain_convergence, interpret_convergence

    st.markdown("#### 🧲 Convergence radar — which domains are colliding, and who sits at the seam")
    # Cross-cutting lenses (e.g. Disruptive Tech) span every sector by design, so they
    # are excluded as poles — otherwise they bridge everything and bury the real seams.
    cross_cutting = {f.label for f in FEEDS if f.cross_cutting}
    seams = domain_convergence(rows, exclude_feeds=cross_cutting)
    if not seams:
        st.caption("_No entity bridges two sector domains in the window yet._")
        return
    st.caption(interpret_convergence(seams))
    if cross_cutting:
        st.caption("_Sector domains only — cross-cutting lenses ("
                   + ", ".join(sorted(cross_cutting)) + ") are excluded as poles._")
    for s in seams:
        d1, d2 = s["domains"]
        bridges = " · ".join(
            f"**{html.escape(b['entity'])}** ({b['mentions']})" for b in s["bridges"]
        )
        st.markdown(
            f"- **{html.escape(d1)} ✕ {html.escape(d2)}** "
            f"<span style='color:#8c959f;font-size:0.78rem'>· {s['n_bridges']} bridging player"
            f"{'s' if s['n_bridges'] != 1 else ''}</span>  \n"
            f"  <span style='font-size:0.85rem'>{bridges}</span>",
            unsafe_allow_html=True,
        )


def _render_comention_chord(rows: list[dict]) -> None:
    """MOT Analyst: the global cross-domain co-mention chord."""
    st.markdown("#### 🕸️ Co-mention network — cross-domain bridges")
    st.caption(
        "Players named together across stories; colour = their dominant feed. Ribbons that "
        "span colours are **cross-domain links** — where an emerging technology or player "
        "bridges domains (the A4 multi-technology signal)."
    )
    if not _comention_chord(rows, top=14):
        st.caption("_Not enough co-mentions in the window yet to draw the network._")


def _render_capital_board(rows: list[dict]) -> None:
    """Named capital-moves board (E2): the actual deals split into full
    commitments (conviction) vs real options (hedged), with a one-line read."""
    from analytics import mot_analyst as ma

    st.markdown("#### 💰 Capital posture — conviction vs hedging")
    board = ma.capital_board(rows)
    if board["shown"] == 0:
        st.caption("_No deal / funding moves to classify in the window._")
        return
    st.caption(ma.interpret_capital(board))

    def _deal_list(items: list[dict], header: str, subtitle: str, color: str) -> None:
        st.markdown(
            f"<span style='color:{color};font-weight:700'>{header}</span> "
            f"<span style='color:#8c959f;font-size:0.8rem'>({len(items)})</span><br>"
            f"<span style='color:#8c959f;font-size:0.78rem'>{subtitle}</span>",
            unsafe_allow_html=True,
        )
        if not items:
            st.caption("_none this window_")
            return
        for m in items[:5]:
            name = f"**{html.escape(str(m['companies'][0]))}** · " if m.get("companies") else ""
            title = (m.get("title") or "").strip()
            title = title[:79] + "…" if len(title) > 80 else title
            st.markdown(
                f"- {name}[{html.escape(title)}]({m.get('url') or '#'}) "
                f"<span style='color:#aeb4bb;font-size:0.72rem'>{html.escape(m.get('feed') or '')}</span>",
                unsafe_allow_html=True,
            )
        if len(items) > 5:
            st.caption(f"…and {len(items) - 5} more")

    col_c, col_o = st.columns(2)
    with col_c:
        _deal_list(board["commitment"], "🟥 Full commitments",
                   "large, irreversible — acquisitions, big capex", "#cf6679")
    with col_o:
        _deal_list(board["option"], "🟦 Real options",
                   "staged, reversible — funding rounds, pilots, partnerships", "#2f80c4")


def _classified_corpus_note() -> None:
    """Standing honesty caption for the news-derived, LLM-classified analytic surfaces —
    so the reader knows the signal's provenance and limits without it being re-stated
    on every exhibit."""
    st.caption(
        "_Derived from **news mentions**, **LLM-classified** via the MOT lens, over a "
        "**partial, recency-pruned** corpus — directional signal, not a complete or audited dataset._"
    )


def render_framework() -> None:
    """🔭 MOT Analyst: the discipline's signature visual frameworks over the
    MOT-lens classifications, each with a templated interpretation, plus a
    per-entity scorecard."""
    from analytics import mot_analyst as ma

    try:
        rows = _framework_rows()
    except Exception as e:
        st.error(f"Could not load data from Supabase: {e}")
        return

    classified = [r for r in rows if r.get("maturity_stage")]

    head, ctrl = st.columns([5, 1])
    with head:
        st.markdown("### 🔭 MOT Analyst")
        st.caption(
            f"{len(classified)} of {len(rows)} recent items classified — read through "
            "the S-curve, diffusion/chasm, and strategy frameworks."
        )
        _classified_corpus_note()
    with ctrl:
        classify = st.button("Classify new", key="lens_classify", width="stretch")
    if classify:
        try:
            from analytics.lens import LensClassifier
            with st.spinner("Classifying via the MOT Lens agent…"):
                res = LensClassifier().run(max_items_per_feed=16)
            _framework_rows.clear()
            st.success(f"Classified (per feed): {res}")
            st.rerun()
        except Exception as e:
            st.warning(f"Classification skipped: {e}")

    if not classified:
        st.info(
            "No items classified yet. Apply `database/schema/mot_lens_columns.sql`, set "
            "`TOQAN_MOT_LENS` in `.env` (create the agent from `backend/Agents_prompt/MOT_Lens_Agent.md`), "
            "then click **Classify new** — or run `python backend/lens_run.py` for a full backfill."
        )
        return

    # Scope selector — drives the per-sector views (diffusion / move / browse).
    scope = st.selectbox("Scope", ["All feeds"] + [f.label for f in FEEDS], key="ma_scope")
    scoped = classified if scope == "All feeds" else [
        r for r in classified if r.get("_feed_label") == scope
    ]

    from analytics.tech_layer import placements as tech_placements
    plc = tech_placements(classified)

    # ── LEAD: technologies on the S-curve + the decisive transitions ──
    _render_tech_scurve(plc)
    _render_transitions()

    # ── Everything else is progressive — collapsed by default ──
    with st.expander("🌐 Diffusion & strategic moves"):
        dp = ma.diffusion_points(scoped)
        _chart_block("Diffusion — adopter categories & the chasm",
                     ma.diffusion_chart(dp), ma.interpret_diffusion(dp),
                     "_No adoption-classified items in scope._")
        cells = ma.move_matrix(scoped)
        _chart_block("Strategic moves (maturity × move)",
                     ma.move_chart(cells), ma.interpret_move(cells),
                     "_No strategic-move classifications in scope._")
        st.caption("💰 Capital posture (real options vs commitments) now has its own **Capital** tab.")

    with st.expander("🕸️ Cross-domain links & design convergence"):
        _render_convergence_radar(rows)
        st.divider()
        _render_comention_chord(rows)
        _render_ferment(plc)

    with st.expander("📉 Measured performance & adoption curves"):
        _render_curves()

    with st.expander("🎯 Score an entity (MOT scorecard)"):
        _render_scorecard(classified)

    with st.expander("🔎 Browse classified stories by lens"):
        dim = st.selectbox(
            "Lens", list(_LENS_FIELDS),
            format_func=lambda k: _LENS_FIELDS[k].split(" — ")[0], key="fw_dim",
        )
        values = sorted({(r.get(dim) or _LENS_SKIP[dim]) for r in scoped})
        pick = st.selectbox("Value", values, key="fw_val")
        matches = [r for r in scoped if (r.get(dim) or _LENS_SKIP[dim]) == pick]
        st.caption(f"{len(matches)} items")
        for r in matches[:30]:
            _story_card(r, show_lens=True, show_provenance=True)


def _ms_list(items: list[dict], limit: int = 6) -> None:
    """Compact market-structure / regulation list: company · linked title · feed."""
    if not items:
        st.caption("_none this window_")
        return
    for m in items[:limit]:
        name = f"**{html.escape(str(m['companies'][0]))}** · " if m.get("companies") else ""
        title = (m.get("title") or "").strip()
        title = title[:79] + "…" if len(title) > 80 else title
        badge = (" <span style='color:#cf6679;font-size:0.7rem'>material</span>"
                 if m.get("impact") == "material" else "")
        st.markdown(
            f"- {name}[{html.escape(title)}]({m.get('url') or '#'}) "
            f"<span style='color:#aeb4bb;font-size:0.72rem'>{html.escape(m.get('feed') or '')}</span>{badge}",
            unsafe_allow_html=True,
        )
    if len(items) > limit:
        st.caption(f"…and {len(items) - limit} more")


def _render_reaction_list(reactions: list[dict], muted: bool, limit: int = 6) -> None:
    """Compact deal-reaction list for the Consensus-vs-reality screen: company ·
    measured move · linked title. `muted` (shrugged) greys the move; otherwise it's
    coloured by direction (🟢 up / 🔴 down)."""
    if not reactions:
        st.caption("_none this window_")
        return
    for r in reactions[:limit]:
        pct = r.get("pct") or 0
        if muted:
            color = "#8c959f"
        else:
            color = "#2f9e6d" if r.get("direction") == "up" else "#cf6679"
        title = (r.get("title") or "").strip()
        title = title[:69] + "…" if len(title) > 70 else title
        st.markdown(
            f"- **{html.escape(str(r.get('company') or r.get('symbol') or ''))}** "
            f"<span style='color:{color};font-weight:700;font-size:0.8rem'>{pct:+.1f}%</span> · "
            f"[{html.escape(title)}]({r.get('url') or '#'}) "
            f"<span style='color:#aeb4bb;font-size:0.72rem'>{html.escape(r.get('feed') or '')}</span>",
            unsafe_allow_html=True,
        )
    if len(reactions) > limit:
        st.caption(f"…and {len(reactions) - limit} more")


def render_capital() -> None:
    """💰 Capital & Economics — a consultant-grade read on how capital and the
    market are betting on the next S-curve. Pyramid: executive read → investment
    landscape → funding the future (E1) → deal flow & posture (E2) → market
    validation → structural shifts (D) → company deep-dive. Posture + free
    financials (yfinance), not paid deal data."""
    from analytics import mot_analyst as ma
    import analytics.financials as fa
    from tickers import ticker_for

    st.markdown("### 💰 Capital & Economics")
    _classified_corpus_note()

    try:
        rows = _framework_rows()
    except Exception as e:
        st.error(f"Could not load data from Supabase: {e}")
        return

    posture = ma.capital_posture(rows)
    fins = _company_financials()
    prices = _stock_prices()
    have_fin = bool(fins)
    pts = fa.landscape_points(fins, ticker_for) if have_fin else []

    if posture["flag"] == "none" and not have_fin:
        st.info("No capital moves or financial data in the window yet.")
        return

    # ── §1 EXECUTIVE READ ──────────────────────────────────────────────────
    if have_fin:
        st.markdown(f"> {fa.capital_synthesis(rows, fins, prices, ticker_for)}")
        k = fa.capital_kpis(rows, fins, prices, ticker_for)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Deals (30d)", k["deals"])
        c2.metric("Commit : Option", k["ratio"])
        c3.metric("Top R&D intensity",
                  f"{k['top_rd']['pct']:.0f}%" if k["top_rd"] else "—",
                  k["top_rd"]["entity"] if k["top_rd"] else None)
        c4.metric("Biggest deal reaction",
                  f"{k['biggest_reaction']['pct']:+.1f}%" if k["biggest_reaction"] else "—",
                  k["biggest_reaction"]["company"] if k["biggest_reaction"] else None)
        c5.metric("Tracked market cap", f"${k['total_market_cap'] / 1e12:.1f}T")
    else:
        st.markdown(f"> {ma.interpret_capital(ma.capital_board(rows))}")
        st.caption(
            "_Run `python backend/financials_run.py` (after applying `company_financials.sql` & "
            "`stock_prices.sql`) to unlock R&D intensity, valuation, and market-reaction views._"
        )

    if posture["flag"] == "over-extension":
        st.warning(
            "⚠️ **Over-extension risk** — large, irreversible commitments into an *early / "
            "uncertain* field. **E2:** staged options would buy information before betting big."
        )
    elif posture["flag"] == "timid":
        st.warning(
            "⚠️ **Timid / late** — small options in a *mature* field; the option-value window "
            "may have closed and conviction bets look overdue."
        )
    elif posture["flag"] == "low-confidence":
        st.caption(
            f"_Posture read withheld — only {posture['n']} clearly-typed capital move(s) in the "
            "window; too few to call over-extension or timidity. The deals below stand on their own._"
        )

    # ── §2 INVESTMENT LANDSCAPE (signature exhibit) ────────────────────────
    if have_fin:
        st.divider()
        st.markdown("#### 🗺️ Investment landscape — who's investing, how the market values it")
        chart = fa.landscape_chart(pts)
        if chart is not None:
            st.altair_chart(chart, width="stretch")
            st.caption(
                "Each bubble a tracked company · x = **(R&D + capex) / revenue** (forward "
                "investment) · y = **market cap / revenue** (how richly priced, log) · size = "
                "market cap · colour = sector. Dashed lines = medians. **Top-right** priced for "
                "innovation · **bottom-right** heavy investment the market hasn't paid for · "
                "**top-left** cash cows. _Multiple is crude (P/S, not P/E); non-USD caps "
                "FX-converted._"
            )
        else:
            st.caption("_Not enough companies with revenue + investment data yet._")

    # ── §3 SECTOR ROLLUP (portfolio view) ──────────────────────────────────
    if have_fin:
        st.divider()
        st.markdown("#### 🧭 Sector rollup — capital intensity & valuation by sector")
        roll = fa.sector_rollup(fins, rows, ticker_for)
        sc = fa.sector_landscape_chart(roll)
        if sc is not None:
            st.altair_chart(sc, width="stretch")
        if roll:
            import pandas as _pd
            table = _pd.DataFrame([{
                "Sector": r["sector"],
                "Cos": r["companies"],
                "Market cap": f"${r['market_cap'] / 1e12:.1f}T",
                "Invest %": f"{r['intensity']:.0f}%" if r["intensity"] is not None else "—",
                "Valuation": f"{r['multiple']:.1f}×" if r["multiple"] is not None else "—",
                "R&D %": f"{r['rd']:.0f}%" if r["rd"] is not None else "—",
                "Deals C:O": f"{r['commitment']}:{r['option']}",
            } for r in roll])
            st.dataframe(table, hide_index=True, width="stretch")
        st.caption(
            "Sector **medians** (investment intensity, valuation, R&D) with total market cap "
            "and deal counts (C = commitments, O = real options). The bubbles are the same, "
            "plotted — the company 2×2 above, zoomed out to portfolio level."
        )

        share_rows = fa.market_cap_share(fins, prices, ticker_for)
        donut = fa.market_cap_donut(share_rows)
        if donut is not None:
            st.markdown("**🍩 Share of tracked market cap — and how it's shifting (30d)**")
            st.altair_chart(donut, width="stretch")
            movers = [s for s in share_rows if s.get("delta") is not None]
            risen = max(movers, key=lambda s: s["delta"], default=None)
            fallen = min(movers, key=lambda s: s["delta"], default=None)
            bits = []
            if risen and risen["delta"] > 0:
                bits.append(f"📈 **{risen['sector']}** {risen['delta']:+.1f}pp")
            if fallen and fallen["delta"] < 0:
                bits.append(f"📉 **{fallen['sector']}** {fallen['delta']:+.1f}pp")
            st.caption(
                ("Each sector's share of the tracked universe's market cap · " + " · ".join(bits)
                 + " over ~30d (price-weighted). Share of *tracked value*, not product market share.")
                if bits else
                "Each sector's share of the tracked universe's market cap (price-weighted; "
                "share of *tracked value*, not product market share).")

    # ── §4 FUNDING THE FUTURE (E1) ─────────────────────────────────────────
    if have_fin:
        st.divider()
        st.markdown("#### 🧪 Funding the next curve — investment intensity (E1)")
        ic = fa.investment_intensity_chart(pts)
        if ic is not None:
            st.altair_chart(ic, width="stretch")
            st.caption(
                "R&D + capex as a share of revenue (top 15). Dashed line = median. High = "
                "plowing revenue into the next S-curve; low = harvesting today's."
            )
        else:
            st.caption("_No investment-intensity data yet._")

    # ── §5 DEAL FLOW & POSTURE (E2) ────────────────────────────────────────
    st.divider()
    st.markdown("#### 🌊 Deal flow & posture — real options vs commitments (E2)")
    fc = fa.deal_flow_chart(fa.deal_flow_timeline(rows, weeks=8))
    if fc is not None:
        st.altair_chart(fc, width="stretch")
        st.caption("Weekly capital moves — 🟥 commitments (conviction) vs 🟦 real options (hedged).")
    else:
        st.caption("_No dated capital moves in the window._")

    with st.expander("Deal board & where capital is concentrating"):
        _render_capital_board(rows)
        st.markdown("**📍 Where capital is concentrating**")
        conc = ma.capital_concentration(rows)

        def _conc(items: list[dict], field: str) -> None:
            ch = ma.concentration_chart(items, field)
            if ch is not None:
                st.altair_chart(ch, width="stretch")
            else:
                st.caption("_none_")

        cf, ce = st.columns(2)
        with cf:
            st.markdown("_By domain_")
            _conc(conc["by_feed"], "feed")
        with ce:
            st.markdown("_By player_")
            _conc(conc["by_entity"], "entity")

    # ── §6 CONSENSUS VS. REALITY (contrarian screen) ───────────────────────
    st.divider()
    st.markdown("#### 📈 Consensus vs. reality — material deals the market shrugged at")
    if prices:
        reactions = fa.deal_reactions(rows, prices, ticker_for, window=3)
        if reactions:
            div = fa.consensus_divergence(reactions)
            st.markdown(f"> {fa.interpret_divergence(div, threshold=2.0)}")

            shrug, conf = st.columns(2)
            with shrug:
                st.markdown(
                    "<span style='color:#cf6679;font-weight:700'>🔴 Market shrugged</span> "
                    f"<span style='color:#8c959f;font-size:0.8rem'>({div['n_shrugged']}) — contrarian watch</span><br>"
                    "<span style='color:#8c959f;font-size:0.78rem'>we said material · the market didn't pay</span>",
                    unsafe_allow_html=True)
                _render_reaction_list(div["shrugged"], muted=True)
            with conf:
                st.markdown(
                    "<span style='color:#2f9e6d;font-weight:700'>🟢 Market confirmed</span> "
                    f"<span style='color:#8c959f;font-size:0.8rem'>({div['n_confirmed']}) — consensus agrees</span><br>"
                    "<span style='color:#8c959f;font-size:0.78rem'>material call · the stock re-priced</span>",
                    unsafe_allow_html=True)
                _render_reaction_list(div["confirmed"], muted=False)

            with st.expander("Event study — every measured reaction"):
                rc = fa.reaction_chart(reactions)
                if rc is not None:
                    st.altair_chart(rc, width="stretch")
                st.caption(
                    "Move from the close before each material deal to ~3 trading days after — an "
                    "approximate event study (other news moves prices too). 🟢 up · 🔴 down · ⚪ flat."
                )
        else:
            st.caption("_No material deals about tracked, priced companies in the window._")
    else:
        st.caption("_Price history not loaded — run `python backend/financials_run.py`._")

    # ── §7 STRUCTURAL SHIFTS (D) ───────────────────────────────────────────
    st.divider()
    st.markdown("#### 🏛️ Structural shifts — market structure & regulation (D)")
    ms = ma.market_structure(rows)
    st.caption(ma.interpret_market_structure(ms))
    mc, mr = st.columns(2)
    with mc:
        st.markdown(
            "<span style='color:#cf6679;font-weight:700'>🔀 Concentrating moves</span> "
            f"<span style='color:#8c959f;font-size:0.8rem'>({ms['counts']['concentrating']})</span><br>"
            "<span style='color:#8c959f;font-size:0.78rem'>M&A / consolidation — fewer, larger players</span>",
            unsafe_allow_html=True,
        )
        _ms_list(ms["concentrating"])
    with mr:
        st.markdown(
            "<span style='color:#e0a458;font-weight:700'>⚖️ Regulation / market failure</span> "
            f"<span style='color:#8c959f;font-size:0.8rem'>({ms['counts']['regulatory']})</span><br>"
            "<span style='color:#8c959f;font-size:0.78rem'>rules of the game shifting</span>",
            unsafe_allow_html=True,
        )
        _ms_list(ms["regulatory"])

    # ── §8 COMPANY DEEP-DIVE ───────────────────────────────────────────────
    if have_fin:
        st.divider()
        st.markdown("#### 🔬 Company deep-dive")
        names = sorted(f["entity"] for f in fins if f.get("entity"))
        pick = st.selectbox("Company", names, key="cap_scorecard")
        card = fa.company_scorecard(pick, fins, prices, rows, ticker_for)
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Market cap",
                  f"${card['market_cap'] / 1e12:.2f}T" if card.get("market_cap") else "—")
        s2.metric("Valuation (P/S)",
                  f"{card['multiple']:.1f}×" if card.get("multiple") else "—")
        s3.metric("R&D intensity",
                  f"{card['rd_intensity'] * 100:.0f}%" if card.get("rd_intensity") is not None else "—")
        s4.metric("Invest. intensity",
                  f"{card['investment_intensity'] * 100:.0f}%" if card.get("investment_intensity") is not None else "—")
        bits = []
        if card.get("sector"):
            bits.append(f"Sector: **{card['sector']}**")
        if card.get("cash"):
            bits.append(f"Cash: **${card['cash'] / 1e9:,.0f}B**")
        bits.append(f"R&D posture: **{card['signal']}**")
        if card.get("reaction"):
            bits.append(f"Latest deal reaction: **{card['reaction']['pct']:+.1f}%**")
        st.caption(" · ".join(bits))

    # ── §9 UNIVERSE COVERAGE — how much of the feeds' companies we price ──────
    from tickers import ticker_coverage, TICKERS
    cov = ticker_coverage(rows)
    with st.expander(f"🛰️ Universe coverage — {len(TICKERS)} tracked tickers"):
        if cov["mentions"]:
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("Mention coverage",
                       f"{cov['coverage'] * 100:.0f}%" if cov["coverage"] is not None else "—",
                       f"{cov['tracked_mentions']} of {cov['mentions']}", delta_color="off")
            cc2.metric("Tracked cos in window", cov["tracked_entities"])
            cc3.metric("Untracked cos", cov["untracked_entities"])
            if cov["top_untracked"]:
                st.caption(
                    "**Most-mentioned companies we don't price yet** — the data-driven shortlist "
                    "for widening the universe (add to `tickers.py`); auto-mapping resolves the rest:")
                st.markdown("\n".join(
                    f"- **{html.escape(str(name))}** · {n} mention{'s' if n != 1 else ''}"
                    for name, n in cov["top_untracked"]))
            else:
                st.caption("Every company mentioned in the window resolves to a tracked ticker.")
        else:
            st.caption("_No company mentions in the window yet._")


@st.cache_data(ttl=300, show_spinner=False)
def _predictions() -> list[dict]:
    """The forecast ledger (paginated past the 1000-row cap). Empty if not set up."""
    out: list[dict] = []
    try:
        sb = _supabase()
        start = 0
        while True:
            chunk = (sb.table("predictions").select("*")
                     .order("made_on", desc=True).range(start, start + 999).execute().data or [])
            out += chunk
            if len(chunk) < 1000:
                break
            start += 1000
    except Exception:
        return []
    return out


def _today_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat()


def _resolve_manual(pred_id: int, outcome: str) -> None:
    try:
        _supabase().table("predictions").update({
            "status": "resolved", "outcome": outcome,
            "resolved_on": _today_iso(), "resolution_note": "manually graded",
        }).eq("id", pred_id).execute()
        _predictions.clear()
    except Exception as e:
        st.error(f"Could not resolve: {e}")


def render_forecasts() -> None:
    """🔮 Forecasts — an accountable foresight deliverable: forward view + hero
    calls, a plain-English credibility scorecard (per-category, so price calls
    can't flatter the record), a horizon timeline, category-grouped cards, and
    methodology."""
    import analytics.forecasts as fc

    head, ctrl = st.columns([5, 1])
    with head:
        st.markdown("### 🔮 Forecasts")
    with ctrl:
        run = st.button("↻ Generate & resolve", key="fc_run", width="stretch")
    if run:
        try:
            import forecast_run
            with st.spinner("Generating & resolving forecasts…"):
                added = forecast_run.generate(_supabase(), _today_iso())
                done = forecast_run.resolve(_supabase(), _today_iso())
            _predictions.clear()
            st.success(f"Added {added} new forecast(s); resolved {done}.")
            st.rerun()
        except Exception as e:
            st.warning(f"Run failed: {e}")

    preds = _predictions()
    if not preds:
        st.info(
            "No forecasts yet. Apply `database/schema/predictions.sql`, then click **Generate & "
            "resolve** (or run `python backend/forecast_run.py`) to start the ledger."
        )
        return

    tr = fc.track_record(preds)
    resolved = [p for p in preds if p.get("status") == "resolved"]
    open_preds = [p for p in preds if p.get("status") != "resolved"]

    # ── §1 FORWARD VIEW ────────────────────────────────────────────────────
    st.markdown(f"> {fc.forecast_summary(preds, tr)}")
    hero = sorted([p for p in open_preds if (p.get("confidence") or 0) >= 0.7],
                  key=lambda p: -(p.get("confidence") or 0))[:3]
    if hero:
        for col, p in zip(st.columns(len(hero)), hero):
            col.markdown(
                f"<div style='border-left:3px solid #2f80c4;padding-left:8px'>"
                f"<span style='font-size:0.7rem;color:#8c959f'>{int((p.get('confidence') or 0) * 100)}% · "
                f"by {p.get('resolve_by')}</span><br><b>{html.escape((p.get('claim') or '')[:130])}</b></div>",
                unsafe_allow_html=True)

    # ── §2 CREDIBILITY SCORECARD ───────────────────────────────────────────
    st.divider()
    st.markdown("#### 📊 Credibility scorecard")
    # The headline accuracy % is too swingy below a credible base (at N=4 one flip moves
    # it 25pp), so it's withheld until the shared floor — the ✓/✗ tally still shows the record.
    show_acc = tr["accuracy"] is not None and tr["resolved"] >= fc.HEADLINE_ACCURACY_FLOOR
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Open", tr["open"])
    k2.metric("Resolved", tr["resolved"])
    k3.metric("Accuracy", f"{tr['accuracy'] * 100:.0f}%" if show_acc else "—",
              f"{tr['hits']}✓ / {tr['misses']}✗" if tr["resolved"] else None)
    k4.metric("Brier", f"{tr['brier']:.3f}" if tr["brier"] is not None else "—",
              "lower = better", delta_color="off")
    st.caption("_Headline excludes quarantined price calls (shown separately by category below)"
               + (f" — {tr['quarantined_resolved']} resolved held out._"
                  if tr.get("quarantined_resolved") else "._"))
    if 0 < tr["resolved"] < fc.HEADLINE_ACCURACY_FLOOR:
        st.caption(f"_Headline accuracy holds until **≥{fc.HEADLINE_ACCURACY_FLOOR} resolved** (have "
                   f"{tr['resolved']}) — below that a single flip swings it too far; the ✓/✗ "
                   "tally is the honest record so far._")

    cats = [c for c in fc.track_record_by_category(preds) if c["total"]]
    if cats:
        import pandas as _pd
        ct = _pd.DataFrame([{
            "Category": c["category"], "Open": c["open"], "Resolved": c["resolved"],
            "Accuracy": f"{c['accuracy'] * 100:.0f}%" if c["accuracy"] is not None else "—",
            "Brier": f"{c['brier']:.2f}" if c["brier"] is not None else "—",
        } for c in cats])
        st.dataframe(ct, hide_index=True, width="stretch")
        st.caption("Accuracy **by category** — quarantined price calls are excluded from the headline "
                   "above and scored only here, so they can't flatter or poison it. Over time this "
                   "shows which kinds of forecast have real skill.")
    if tr["resolved"] >= 4:
        ch = fc.calibration_chart(fc.calibration_bins(resolved))
        if ch is not None:
            st.altair_chart(ch, width="stretch")
            st.caption("On the dashed line = well-calibrated · above = under-confident · below = over-confident.")
    else:
        st.caption(f"_Calibration curve unlocks at ≥4 resolved forecasts (have {tr['resolved']}) — "
                   "the record compounds as they come due._")

    # ── §3 THE CALLS — actionable few up top, the rest in a scannable table ──
    st.divider()
    st.markdown(f"#### 🟡 Open forecasts ({len(open_preds)})")

    # Strategist calls that are overdue need manual grading — the only interactive
    # part, so they get their own section instead of being buried in the list.
    needs = [p for p in open_preds
             if p.get("kind") == "manual" and fc.is_overdue(p, _today_iso())]
    if needs:
        st.markdown(f"**⏳ Needs your grading ({len(needs)})** — overdue Strategist calls:")
        for p in needs:
            st.markdown(
                f"- **{html.escape(p.get('claim') or '')}**  \n"
                f"  <span style='color:#8c959f;font-size:0.74rem'>made {p.get('made_on')} · "
                f"due {p.get('resolve_by')}</span>",
                unsafe_allow_html=True)
            b1, b2, b3, _sp = st.columns([1, 1, 1, 5])
            if b1.button("✓ Hit", key=f"res_{p['id']}_hit"):
                _resolve_manual(p["id"], "hit")
                st.rerun()
            if b2.button("✗ Miss", key=f"res_{p['id']}_miss"):
                _resolve_manual(p["id"], "miss")
                st.rerun()
            if b3.button("~ Partial", key=f"res_{p['id']}_partial"):
                _resolve_manual(p["id"], "partial")
                st.rerun()
        st.divider()

    if open_preds:
        import pandas as _pd
        table = fc.open_forecast_table(open_preds)
        cats = ["All"] + sorted({r["Category"] for r in table})
        pick = st.selectbox("Filter by category", cats, key="fc_cat_filter")
        shown = table if pick == "All" else [r for r in table if r["Category"] == pick]
        st.dataframe(
            _pd.DataFrame(shown),
            hide_index=True, width="stretch",
            column_config={
                "Forecast": st.column_config.TextColumn("Forecast", width="large"),
                "Conf %": st.column_config.ProgressColumn(
                    "Conf", min_value=0, max_value=100, format="%d%%"),
            },
        )
        st.caption("Sortable — click a column header. Price calls are quarantined in their own "
                   "category so they can't flatter the headline.")
    else:
        st.caption("_No open forecasts._")

    # ── §4 RESOLVED RECEIPTS ───────────────────────────────────────────────
    st.divider()
    with st.expander(f"✅ Resolved forecasts — the receipts ({len(resolved)})"):
        badge = {"hit": "🟢 HIT", "miss": "🔴 MISS", "partial": "🟡 PARTIAL"}
        for p in sorted(resolved, key=lambda x: str(x.get("resolved_on") or ""), reverse=True)[:60]:
            st.markdown(
                f"- {badge.get(p.get('outcome'), '?')} · **{html.escape(p.get('claim') or '')}**  \n"
                f"  <span style='color:#8c959f;font-size:0.74rem'>made {p.get('made_on')} @ "
                f"{int((p.get('confidence') or 0) * 100)}% · resolved {p.get('resolved_on')} · "
                f"{html.escape(p.get('resolution_note') or '')}</span>",
                unsafe_allow_html=True,
            )
        if not resolved:
            st.caption("_None resolved yet._")

    # ── §5 METHODOLOGY ─────────────────────────────────────────────────────
    with st.expander("📐 Methodology — what we forecast, and what we don't"):
        st.markdown(
            "- **What we forecast** — things with inertia and theory behind them: technology "
            "adoption (S-curve / diffusion), market structure (consolidation, capital posture), "
            "deal flow, and market *reactivity* (whether deals move the stock).\n"
            "- **What we deliberately don't** — short-term **stock-price direction**. Markets are "
            "~efficient over weeks/months, so those are near coin-flips. We *do* log them (at 50% "
            "confidence) but quarantine them in the **Price (low-signal)** category — excluded from "
            "the headline accuracy/Brier, scored only in their own row — so they can't flatter or "
            "poison the headline, and the per-category accuracy shows their true skill.\n"
            "- **How we score** — every forecast is locked when made (no edits) with an explicit "
            "resolve-by date. Auto kinds resolve objectively against our own data; Strategist calls "
            "are graded by hand. Accuracy + Brier + calibration, per MOT §G (epistemic rigour).\n"
            "- **Self-improving** — each auto generator's stated confidence is recalibrated toward "
            "its *own realized hit-rate* (shrinkage-blended by sample size, bounded ±20pts), so the "
            "calls get better-calibrated as the record grows — the loop closes on itself. Price "
            "calls stay pinned at 50% as the un-recalibrated baseline; you'll see the adjustment in "
            "a forecast's basis (e.g. _“recalibrated 60→66%”_)."
        )


# ── Composed tabs ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def _watchlist_alerts() -> list[dict]:
    from analytics.watchlist import Watchlist
    return Watchlist(_supabase()).alerts()


def _render_watchlist() -> None:
    """🔔 Watchlist manager + alert preview (push happens in the scheduled job)."""
    from analytics.watchlist import Watchlist
    from technologies import TECHNOLOGIES, TECH_BY_KEY

    wl = Watchlist(_supabase())
    items = wl.items()
    n_alerts = 0
    try:
        n_alerts = len(_watchlist_alerts())
    except Exception:
        pass
    label = "🔔 Watchlist & alerts" + (f" — {n_alerts} new" if n_alerts else "")
    with st.expander(label):
        try:
            alerts = _watchlist_alerts()
        except Exception:
            alerts = []
        if alerts:
            # Story alerts are windowed to the last 8h; stage transitions are current
            # watch-items (not time-windowed), so label the two honestly rather than
            # claiming everything fired in the last 8h.
            n_tr = sum(1 for a in alerts if a["type"] == "transition")
            n_story = len(alerts) - n_tr
            bits = ([f"{n_story} new story alert(s) (last 8h)"] if n_story else []) + \
                   ([f"{n_tr} current stage transition(s)"] if n_tr else [])
            st.markdown(f"**{' · '.join(bits)}:**")
            for a in alerts[:10]:
                if a["type"] == "transition":
                    st.markdown(f"- 🔀 **{a['subject']}** — {a.get('detail', '')}")
                else:
                    feed = f" [{a['feed']}]" if a.get("feed") else ""
                    st.markdown(f"- **{a['subject']}**{feed}: [{a.get('title', '')}]({a.get('url', '#')})")
        elif items:
            st.caption("No alerts in the last 8h.")

        if items:
            st.markdown("**Tracking:**")
            for it in items:
                disp = (TECH_BY_KEY[it["value"]].label
                        if it["kind"] == "technology" and it["value"] in TECH_BY_KEY else it["value"])
                row, btn = st.columns([6, 1])
                row.markdown(f"- `{it['kind']}` · {disp}")
                if btn.button("✕", key=f"wl_rm_{it['id']}"):
                    wl.remove(it["kind"], it["value"])
                    _watchlist_alerts.clear()
                    st.rerun()
        else:
            st.caption("Nothing tracked yet — add a technology, entity, or feed:")

        kind = st.selectbox("Track a…", ["technology", "entity", "feed"], key="wl_kind")
        if kind == "technology":
            opts = {t.label: t.key for t in TECHNOLOGIES}
            val = opts[st.selectbox("Technology", list(opts), key="wl_v_tech")]
        elif kind == "feed":
            val = st.selectbox("Feed", [f.label for f in FEEDS], key="wl_v_feed")
        else:
            val = st.text_input("Entity (company name)", key="wl_v_ent").strip()
        if st.button("➕ Track", key="wl_add") and val:
            wl.add(kind, val)
            _watchlist_alerts.clear()
            st.rerun()
        st.caption(
            "Alerts are pushed by the scheduled job when `ALERT_WEBHOOK` is set; this panel "
            "previews new story alerts (last 8h) plus any current stage transitions."
        )


def render_calibration_banner() -> None:
    """🎯 The lead credibility hook — the public, falsifiable forecast track record
    (accuracy + Brier + the per-category calibration cut) surfaced at the *top* of
    the Briefing. This is the one thing incumbents structurally won't do: grade
    themselves. The full ledger lives in 🔮 Forecasts; this is the proof, up front."""
    import analytics.forecasts as fc

    h = fc.calibration_headline(_predictions())
    st.markdown(
        "<div style='border-left:4px solid #2f80c4;padding:2px 0 4px 12px'>"
        "<span style='font-size:1.05rem;font-weight:700'>🎯 The intelligence that grades itself</span>"
        f"<br><span style='color:#8c959f;font-size:0.85rem'>{html.escape(fc.calibration_tagline(h))}</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    if h["resolved"] or h["open"]:
        # Same ≥-floor gate as the Forecasts tab: the lead credibility hook can't headline
        # a swingy accuracy % off a handful of resolved forecasts (the ✓/✗ tally still shows).
        show_acc = h["accuracy"] is not None and h["resolved"] >= fc.HEADLINE_ACCURACY_FLOOR
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Accuracy", f"{h['accuracy'] * 100:.0f}%" if show_acc else "—",
                  f"{h['hits']}✓ / {h['misses']}✗" if h["resolved"] else None)
        k2.metric("Brier", f"{h['brier']:.3f}" if h["brier"] is not None else "—",
                  "lower = better", delta_color="off")
        k3.metric("Resolved", h["resolved"])
        k4.metric("Open", h["open"])

    if h["categories"]:
        parts = []
        for c in h["categories"]:
            acc = f"{c['accuracy'] * 100:.0f}%" if c["accuracy"] is not None else "—"
            wall = ", walled off" if c["category"] == "Price (low-signal)" else ""
            parts.append(f"**{c['category']}** {acc} ({c['resolved']}{wall})")
        st.caption("By category — " + " · ".join(parts)
                   + ". Price calls are quarantined — excluded from the headline stats above, "
                   "scored separately here. Full ledger, calibration curve & methodology in the "
                   "🔮 **Forecasts** tab.")
    else:
        st.caption("Locked when made · auto-resolved against our own data · graded by accuracy, "
                   "Brier & calibration. Full ledger and methodology in the 🔮 **Forecasts** tab.")


def render_briefing() -> None:
    """🧭 Briefing — the accountable track record up top (the lead credibility hook),
    then the Strategist read (what it means), the watchlist, and the overview (what
    happened: stats, feed health, top stories)."""
    render_calibration_banner()
    st.divider()
    render_strategist()
    st.divider()
    _render_watchlist()
    st.markdown("### 📊 Overview")
    render_pulse()


def render_feeds() -> None:
    """📰 Feeds — every feed topic in one tab; pick the feed with the pills up top."""
    labels = [f"{f.icon} {f.label}" for f in FEEDS]
    choice = st.segmented_control(
        "Feed", labels, default=labels[0],
        label_visibility="collapsed", key="feeds_pick",
    ) or labels[0]
    render_feed(FEEDS[labels.index(choice)])


# ── Compare: two entities or two technologies side by side ───────────────────

def _compare_entities() -> None:
    import pandas as pd
    from analytics.entity_tracker import co_mentions, entity_read

    days = _ENTITY_RANGES[st.segmented_control(
        "Range", list(_ENTITY_RANGES), default="90D", key="cmp_ent_range") or "90D"]
    universe = [name for name, _ in _entity_universe(days)]
    if len(universe) < 2:
        st.info("Need at least two tracked entities — refresh the feeds first.")
        return
    c1, c2 = st.columns(2)
    a = c1.selectbox("Entity A", universe, index=0, key="cmp_ent_a")
    b = c2.selectbox("Entity B", universe, index=min(1, len(universe) - 1), key="cmp_ent_b")

    def _panel(col, entity):
        prof = _entity_profile(entity, days)
        sent = prof["sentiment"]
        with col:
            st.markdown(f"### {entity}")
            st.caption(entity_read(entity, prof))
            m1, m2 = st.columns(2)
            m1.metric("Prominence (wtd)", f"{prof.get('weighted', 0):.1f}",
                      help=f"Significance- & source-weighted; {prof['total']} raw mentions in the live window.")
            m2.metric("Feeds", prof["feeds_count"])
            m3, m4 = st.columns(2)
            m3.metric("Positive / negative", f"{sent.get('positive', 0)} / {sent.get('negative', 0)}")
            m4.metric("Reach", "🔗 cross-domain" if prof["feeds_count"] >= 2 else "single feed")
            if prof["by_feed"]:
                st.bar_chart(pd.DataFrame(list(prof["by_feed"].items()),
                                         columns=["feed", "mentions"]).set_index("feed"))
            co = dict(co_mentions(prof["stories"], entity))
            if co:
                st.caption("Top co-mentions: " + ", ".join(
                    f"{k} ({v})" for k, v in sorted(co.items(), key=lambda kv: -kv[1])[:6]))
        return prof, set(co)

    pa, co_a = _panel(c1, a)
    pb, co_b = _panel(c2, b)

    shared_feeds = sorted(set(pa["by_feed"]) & set(pb["by_feed"]))
    shared_co = sorted(co_a & co_b)
    st.markdown("#### 🤝 Overlap")
    st.markdown(
        f"- **Shared feeds:** {', '.join(shared_feeds) or '—'}\n"
        f"- **Co-mentioned with both:** {', '.join(shared_co) or '—'}"
    )


def _compare_technologies() -> None:
    from analytics import mot_analyst as ma
    from analytics.tech_layer import placements as tech_placements, display_stage
    from technologies import TECH_BY_KEY
    from benchmarks import BENCHMARKS

    classified = [r for r in _framework_rows() if r.get("maturity_stage")]
    plc = {p["label"]: p for p in tech_placements(classified)}
    if len(plc) < 2:
        st.info("Not enough classified technologies yet — run the MOT lens first.")
        return
    labels = list(plc)
    c1, c2 = st.columns(2)
    a = c1.selectbox("Technology A", labels, index=0, key="cmp_tech_a")
    b = c2.selectbox("Technology B", labels, index=min(1, len(labels) - 1), key="cmp_tech_b")
    key_by_label = {t.label: k for k, t in TECH_BY_KEY.items()}

    def _panel(col, label):
        p = plc[label]
        with col:
            st.markdown(f"### {label}")
            st.caption(f"Domain: {p['domain']}")
            m1, m2 = st.columns(2)
            # Show the centroid-based committed stage — the same value that positions
            # the S-curve dot and the placement table — not the bare modal.
            m1.metric("Maturity", (display_stage(p) or "—").replace("-", " "))
            m2.metric("Adoption", (display_stage(p, "adoption") or "—").replace("-", " "))
            m3, m4 = st.columns(2)
            m3.metric("Coverage", p["articles"])
            m4.metric("Players", p["entrants"])
            st.caption(f"Dominant move: **{(p['move'] or '—').replace('-', ' ')}**")
            spec = BENCHMARKS.get(key_by_label.get(label, ""))
            chart = ma.benchmark_chart(spec) if spec else None
            if chart is not None:
                st.altair_chart(chart, width="stretch")
                st.caption(f"{spec['metric']} ({spec['unit']}) — _illustrative_")
            else:
                st.caption("_No measured performance series seeded — add one in `benchmarks.py`._")

    _panel(c1, a)
    _panel(c2, b)
    # Rank by S-curve position — the centroid that places the dot — so the Read agrees
    # with the chart and the committed-stage metric, not the bare modal (which can flip
    # the order on a bimodal spread).
    ra, rb = ma.scurve_position(plc[a]), ma.scurve_position(plc[b])
    if ra is not None and rb is not None and round(ra, 3) != round(rb, 3):
        ahead, behind = (a, b) if ra > rb else (b, a)
        st.markdown(f"#### 🧭 Read\n**{ahead}** is further along the S-curve than **{behind}**.")


def render_compare() -> None:
    """⚖️ Compare two entities or two technologies side by side."""
    mode = st.radio("Compare", ["Entities", "Technologies"], horizontal=True,
                    key="cmp_mode", label_visibility="collapsed")
    if mode == "Entities":
        _compare_entities()
    else:
        _compare_technologies()


def render_ask() -> None:
    """💬 Ask Lodestar — a conversational analyst over the feeds + MOT theory."""
    import os

    st.markdown("### 💬 Ask Lodestar")
    st.caption(
        "Ask anything about the tracked domains — answered over a **retrieved slice** of the "
        "feeds + MOT theory (the most relevant recent stories & passages, not the whole "
        "corpus), with citations. No web search."
    )
    history = st.session_state.setdefault("ask_history", [])
    for turn in history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])

    q = st.chat_input("e.g. What's the state of solid-state batteries — should we worry?")
    if not q:
        return
    history.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        if not os.getenv("TOQAN_ASK"):
            msg = ("Set `TOQAN_ASK` in `.env` (create the agent from "
                   "`backend/Agents_prompt/Ask_Lodestar_Agent.md`) to enable Ask.")
            st.info(msg)
            history.append({"role": "assistant", "content": msg})
            return
        try:
            from analytics.ask import AskLodestar
            with st.spinner("Reasoning over the feeds + theory…"):
                res = AskLodestar(_supabase()).answer(q, history=history)
            st.markdown(res["answer"])
            if res["stories"] or res["theory"]:
                with st.expander("Sources"):
                    for s in res["stories"]:
                        st.markdown(
                            f"- **[{s['label']}]** [{s.get('title', '')}]({s.get('url', '#')}) "
                            f"· {s.get('feed', '')}"
                        )
                    for t in res["theory"]:
                        st.markdown(
                            f"- **[{t['label']}]** {_src_name(t.get('source_file'))} "
                            f"· relevance {float(t.get('similarity') or 0):.2f}"
                        )
            history.append({"role": "assistant", "content": res["answer"]})
        except Exception as e:
            err = f"Couldn't answer: {e}"
            st.warning(err)
            history.append({"role": "assistant", "content": err})


def render_explore() -> None:
    """🔍 Explore — trends, entity dossiers, and side-by-side comparison in one tab."""
    inner = st.tabs(["📈 Trends", "🔍 Entities", "⚖️ Compare"])
    with inner[0]:
        render_trends()
    with inner[1]:
        render_entities()
    with inner[2]:
        render_compare()


# ── Page: header + global refresh + the consolidated tabs ────────────────────
hcol_title, hcol_refresh = st.columns([5, 1])
with hcol_title:
    st.markdown("## 📡 Lodestar")
    st.caption("Signals that move markets — across tech, energy, and beyond.")
with hcol_refresh:
    refresh_all = st.button("🔄 Refresh all", width="stretch", key="refresh_all")

# Last-refresh status. The scheduled GitHub Action is the source of truth; the
# in-app buttons are for ad-hoc top-ups (and a closed tab can lose an in-app run).
try:
    _last_fetch = _feeds_last_fetched()
except Exception:
    _last_fetch = None
st.caption(
    f"Feeds last refreshed {_format_fetched(_last_fetch)} · auto-refreshed every 6h by GitHub Actions."
    if _last_fetch
    else "No feed data yet · the scheduled GitHub Action (or **Refresh all**) populates the feeds."
)

if refresh_all:
    # Full pipeline in one click (everything except alerts): feeds → MOT lens →
    # rollup → Strategist → financials → forecasts, in dependency order. Feeds run
    # in parallel threads (~7x faster than serial); per-stage UI updates would be
    # unsafe from worker threads, so feed progress is per-feed. Each downstream stage
    # degrades independently — a missing key skips that stage, never the whole run.
    runnable = [f for f in FEEDS if f.api_key]
    skipped = [f for f in FEEDS if not f.api_key]
    if not runnable:
        st.warning("No feeds have an API key set in `.env`.")
    else:
        n = len(runnable)
        ok: list[tuple[Feed, dict]] = []
        failed: list[tuple[Feed, Exception]] = []
        notes: list[str] = []
        with st.status(f"Refreshing {n} feeds in parallel…", expanded=True) as status:
            with ThreadPoolExecutor(max_workers=n) as ex:
                futures = {ex.submit(run_refresh, f): f for f in runnable}
                done = 0
                for fut in as_completed(futures):
                    feed = futures[fut]
                    done += 1
                    try:
                        res = fut.result()
                        ok.append((feed, res))
                        status.write(
                            f"✓ [{done}/{n}] {feed.label} · {res['items_parsed']} parsed · "
                            f"{res['rows_upserted']} upserted"
                        )
                    except Exception as e:
                        logger.exception("Refresh failed for %s", feed.key)
                        failed.append((feed, e))
                        status.write(f"✗ [{done}/{n}] {feed.label} · {e}")

            # MOT-lens classify the new rows FIRST, so the rollup, Strategist and
            # S-curve all reason over the freshly-classified articles this cycle.
            status.update(label="Classifying new articles (MOT lens)…")
            try:
                from analytics.lens import LensClassifier
                lens_res = LensClassifier().run(max_items_per_feed=16)
                status.write(f"✓ MOT lens classified: {lens_res}")
            except Exception as e:
                logger.warning("Lens classify skipped: %s", e)
                notes.append("lens skipped (set TOQAN_MOT_LENS)")
                status.write(f"✗ MOT lens skipped · {e}")

            status.update(label="Rebuilding analytics (rollup + Strategist)…")
            try:
                from analytics.rollup import RollupBuilder
                RollupBuilder(_supabase()).run()
            except Exception:
                logger.exception("Rollup rebuild failed")
                notes.append("rollup failed")
            try:
                from analytics.strategist import Strategist
                Strategist(_supabase()).generate()
            except Exception as e:
                logger.warning("Strategist read skipped: %s", e)
                notes.append("strategist skipped (set TOQAN_STRATEGIST)")

            # Free yfinance enrichment → 💰 Capital (market caps, prices, R&D).
            status.update(label="Enriching financials (yfinance)…")
            try:
                import financials_run
                fr = financials_run.run(_supabase())
                status.write(f"✓ Financials: {fr['fundamentals']}/{fr['tickers']} fundamentals · "
                             f"{fr['prices']} price series")
            except Exception as e:
                logger.warning("Financials enrich skipped: %s", e)
                notes.append("financials skipped")
                status.write(f"✗ Financials skipped · {e}")

            # Generate + resolve forecasts (reads the cached brief; no agent calls).
            status.update(label="Generating & resolving forecasts…")
            try:
                import forecast_run
                _as_of = _today_iso()
                added = forecast_run.generate(_supabase(), _as_of)
                resolved_n = forecast_run.resolve(_supabase(), _as_of)
                status.write(f"✓ Forecasts: +{added} new · {resolved_n} resolved")
            except Exception as e:
                logger.warning("Forecast run skipped: %s", e)
                notes.append("forecasts skipped")
                status.write(f"✗ Forecasts skipped · {e}")

            # Label is honest about partial runs (a stage skipped on a missing key
            # isn't a hard error, so the box only goes red on feed failures).
            done_label = ("Refresh complete" if not notes
                          else "Refresh complete — some stages skipped/failed (see notes)")
            status.update(label=done_label, state=("error" if failed else "complete"))

        for _clear in (
            _feeds_last_fetched, _pulse_snapshot, _latest_strategist, _strategist_recent,
            _trends_rows, _entity_universe, _entity_profile, _framework_rows,
            _company_financials, _stock_prices, _predictions, _watchlist_alerts,
        ):
            _clear.clear()

        parsed = sum(r["items_parsed"] for _, r in ok)
        upserted = sum(r["rows_upserted"] for _, r in ok)
        summary = f"Refreshed {len(ok)}/{n} feeds · {parsed} parsed · {upserted} upserted."
        if skipped:
            summary += f"  Skipped (no key): {', '.join(f.label for f in skipped)}."
        if notes:
            summary += f"  Notes: {', '.join(notes)}."
        if failed:
            summary += f"  Failed: {', '.join(f.label for f, _ in failed)}."
            st.warning(summary)
        else:
            st.success(summary)

_tabs = st.tabs(["🧭 Briefing", "💬 Ask", "🔭 MOT Analyst", "💰 Capital",
                 "🔮 Forecasts", "🔍 Explore", "📰 Feeds"])
with _tabs[0]:
    render_briefing()
with _tabs[1]:
    render_ask()
with _tabs[2]:
    render_framework()
with _tabs[3]:
    render_capital()
with _tabs[4]:
    render_forecasts()
with _tabs[5]:
    render_explore()
with _tabs[6]:
    render_feeds()
