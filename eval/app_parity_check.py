#!/usr/bin/env python3
"""
L10 static parity checker — backend payload fields vs frontend usage.

For every API endpoint ↔ page pair it:
  1. extracts the TOP-LEVEL field names the backend route emits (Python AST:
     the dict literal the route returns, following simple `return name` /
     `return helper()` indirection and `payload["k"] = ...` subscript assigns);
  2. extracts which of those names the page (plus the shared components it
     renders through) actually references (regex over the .tsx sources:
     `.field`, `?.field`, `["field"]`, or `{ field` destructuring);
  3. extracts every `data.<field>` access in the page and flags accesses of
     fields the backend never emits (ghost reads → silent undefined).

Static / offline only — no imports of the app, no network, no .env.

Known false-positive/negative modes (be honest when reading the output):
  • FP "used": a page token that happens to equal a payload key (e.g. a local
    variable `.feeds` on a different object) counts as usage.  Usage is checked
    across the page file + shared components, so a key used only by a *different*
    page sharing the component can also read as used.
  • FN "used": fields renamed through intermediate objects (e.g. spread into
    `{...t, x: t.ax}`) or accessed with a dynamic key (`r[dim]`) are invisible.
  • Ghost-read check only sees accesses on a variable literally named `data`
    (the convention in these pages); `prof.data.x`, destructured aliases, and
    nested-field access are out of scope here (covered manually in the report).
  • Only TOP-LEVEL keys are diffed; nested payloads (kpis.*, board.*, per-item
    fields) are audited by hand in eval/reports/10_app_parity.md.

Usage:  ./venv/bin/python eval/app_parity_check.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "app"
PAGES = ROOT / "frontend" / "src" / "pages"
COMPONENTS = ROOT / "frontend" / "src" / "components"

# endpoint → (backend module, route function name, page file, extra component files
# the page renders payload fields through)
PAIRS: list[dict] = [
    {"endpoint": "GET /api/capital", "module": "capital.py", "func": "capital",
     "page": "Capital.tsx", "components": ["charts.tsx", "ui.tsx"]},
    {"endpoint": "GET /api/forecasts", "module": "forecasts.py", "func": "forecasts",
     "page": "Forecasts.tsx", "components": ["charts.tsx", "ui.tsx"]},
    {"endpoint": "GET /api/explore/trends", "module": "explore.py", "func": "trends",
     "page": "Explore.tsx", "components": ["charts.tsx", "ui.tsx"]},
    {"endpoint": "GET /api/explore/entity", "module": "explore.py", "func": "entity",
     "page": "Explore.tsx", "components": ["charts.tsx", "Story.tsx"]},
    {"endpoint": "GET /api/explore/entities", "module": "explore.py", "func": "entities",
     "page": "Explore.tsx", "components": []},
    {"endpoint": "GET /api/explore/technologies", "module": "explore.py", "func": "technologies",
     "page": "Explore.tsx", "components": []},
    {"endpoint": "GET /api/mot", "module": "mot.py", "func": "mot",
     "page": "Mot.tsx", "components": ["charts.tsx", "ChordDiagram.tsx", "Story.tsx"]},
    {"endpoint": "GET /api/mot/scorecard-read", "module": "mot.py", "func": "scorecard_read",
     "page": "Mot.tsx", "components": []},
    {"endpoint": "GET /api/briefing", "module": "briefing.py", "func": "briefing",
     "page": "Briefing.tsx", "components": ["Story.tsx", "ui.tsx"]},
    {"endpoint": "GET /api/feeds", "module": "feeds_api.py", "func": "feeds",
     "page": "Feeds.tsx", "components": ["Story.tsx"]},
    {"endpoint": "POST /api/ask", "module": "feeds_api.py", "func": "ask",
     "page": "Ask.tsx", "components": []},
]

# Keys that are metadata echoes rather than exhibits — reported, but tagged.
ECHO_KEYS = {"scope", "feed", "weighted", "entity", "days", "as_of"}


# ── backend: top-level keys of the dict a route returns ─────────────────────────
def _dict_keys(node: ast.Dict) -> set[str]:
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _keys_from_func(fn: ast.FunctionDef, module: ast.Module) -> set[str]:
    """Union of top-level keys over every `return {...}` in fn, following
    `return name` (dict built in fn, incl. `name["k"] = ...`) and
    `return helper()` (module-level helper) one level deep."""
    keys: set[str] = set()
    module_funcs = {f.name: f for f in module.body if isinstance(f, ast.FunctionDef)}

    def keys_for_name(name: str) -> set[str]:
        out: set[str] = set()
        for sub in ast.walk(fn):
            # payload: dict = {...} / payload = {...}
            if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name) \
                    and sub.target.id == name and isinstance(sub.value, ast.Dict):
                out |= _dict_keys(sub.value)
            if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Dict) \
                    and any(isinstance(t, ast.Name) and t.id == name for t in sub.targets):
                out |= _dict_keys(sub.value)
            # payload["k"] = ...
            if isinstance(sub, ast.Assign):
                for t in sub.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                            and t.value.id == name and isinstance(t.slice, ast.Constant):
                        out.add(t.slice.value)
        return out

    for sub in ast.walk(fn):
        if not isinstance(sub, ast.Return) or sub.value is None:
            continue
        v = sub.value
        if isinstance(v, ast.Dict):
            keys |= _dict_keys(v)
        elif isinstance(v, ast.Name):
            keys |= keys_for_name(v.id)
        elif isinstance(v, ast.Call) and isinstance(v.func, ast.Name) \
                and v.func.id in module_funcs:
            keys |= _keys_from_func(module_funcs[v.func.id], module)
    return keys


def backend_keys(module_file: str, func: str) -> set[str]:
    tree = ast.parse((BACKEND / module_file).read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func:
            return _keys_from_func(node, tree)
    raise SystemExit(f"route function {func} not found in {module_file}")


# ── frontend: is a key referenced? which data.<x> accesses exist? ───────────────
def page_source(pair: dict) -> str:
    src = (PAGES / pair["page"]).read_text()
    for c in pair["components"]:
        src += "\n" + (COMPONENTS / c).read_text()
    return src


def key_used(src: str, key: str) -> bool:
    pats = [
        rf"[\w\)\]]\??\.{re.escape(key)}\b",     # data.key / data?.key / foo().key
        rf"\[\s*[\"']{re.escape(key)}[\"']\s*\]",  # data["key"]
        rf"\{{[^}}]*\b{re.escape(key)}\b[^}}]*\}}\s*=",  # const { key } = data
    ]
    return any(re.search(p, src) for p in pats)


def data_accesses(page_file: str) -> set[str]:
    """Every `data.<field>` / `data?.<field>` access in the page file itself."""
    src = (PAGES / page_file).read_text()
    return set(re.findall(r"\bdata\??\.(\w+)", src))


# ── report ───────────────────────────────────────────────────────────────────────
def main() -> int:
    findings = 0
    # ghost-read check needs, per page, the union of keys across that page's endpoints
    keys_by_page: dict[str, set[str]] = {}
    for pair in PAIRS:
        pair["keys"] = backend_keys(pair["module"], pair["func"])
        keys_by_page.setdefault(pair["page"], set()).update(pair["keys"])

    for pair in PAIRS:
        src = page_source(pair)
        unused = sorted(k for k in pair["keys"] if not key_used(src, k))
        print(f"\n== {pair['endpoint']}  ↔  pages/{pair['page']} ==")
        print(f"   emitted top-level fields ({len(pair['keys'])}): {', '.join(sorted(pair['keys']))}")
        if unused:
            findings += len(unused)
            for k in unused:
                tag = " [metadata echo]" if k in ECHO_KEYS else ""
                print(f"   UNUSED by UI: {k}{tag}")
        else:
            print("   all fields referenced by the UI (or a shared component)")

    print("\n== ghost reads (page accesses `data.<x>` the endpoint never emits) ==")
    ghosts = 0
    for page, keys in sorted(keys_by_page.items()):
        # useResource/PageChrome hand the payload to the page as `data`
        acc = data_accesses(page)
        ghost = sorted(a for a in acc if a not in keys)
        # `data` is also used for hook results ({data,loading}) in Explore — drop
        # the hook-envelope fields to keep the signal honest.
        ghost = [g for g in ghost if g not in {"data", "loading", "error", "universe", "technologies"}]
        if ghost:
            ghosts += len(ghost)
            print(f"   {page}: {', '.join(ghost)}")
    if not ghosts:
        print("   none found")

    print(f"\nTotal top-level unused-field findings: {findings}; ghost reads: {ghosts}")
    print("(Nested-field + interaction findings live in eval/reports/10_app_parity.md.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
