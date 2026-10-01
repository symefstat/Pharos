"""
L1 prompt audit — mechanical schema-drift check (offline, read-only).

Extracts the declared output fields + enum vocabularies from each prompt in
`Agents_prompt/` and diffs them against what the downstream code actually
parses:

  - 10 feed extractors  → home_news/parser.py  (canonical keys, sentiment /
                          business_impact / scope vocab, JSON-array shape)
  - MOT_Lens_Agent.md   → analytics/lens.py    (_MATURITY / _ADOPTION / _MOVE,
                          reconcile_batch keys, LENS_PROMPT_VERSION literal)
  - Strategist_Agent.md → analytics/strategist.py (_ACTIONS / _IMPACT /
                          _HORIZON / _CONFIDENCE, top-level + signal keys)

Ask_Lodestar_Agent.md returns prose (no parser), so it has no mechanical
contract to diff — it is intentionally skipped.

Usage (from repo root):
    ./venv/bin/python eval/judges/prompt_audit.py
Exit code 0 = no drift; 1 = at least one mismatch (each printed as DRIFT).

Enum vocabularies are imported/parsed from the pipeline itself so this script
can never drift from the source of truth. No network, no Supabase, no Toqan.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from home_news.parser import _BUSINESS_IMPACT_VALUES, _SCOPE_VALUES  # noqa: E402

PROMPTS_DIR = REPO / "Agents_prompt"

EXTRACTOR_PROMPTS = [
    "AI_Energy_Impact_Feed_Agent.md",
    "Biotech_Health_Feed_Agent.md",
    "Climate_Energy_Feed_Agent.md",
    "Defense_Space_Feed_Agent.md",
    "Disruptive_Tech_Feed_Agent.md",
    "EV_Developments_Feed_Agent.md",
    "Fintech_Digital_Assets_Feed_Agent.md",
    "Geopolitics_Trade_Feed_Agent.md",
    "Semiconductor_News_Feed_Agent.md",
    "Software_Cyber_Feed_Agent.md",
]

# Canonical item keys the parser resolves (home_news/parser.py:_build_item /
# HomeNewsItem.to_row). Aliases (headline/link/date/source/category…) are
# tolerated by the parser but count as key drift, so they are NOT listed here.
PARSER_KEYS = frozenset({
    "title", "summary", "url", "source_name", "published_at", "country",
    "tags", "companies", "sentiment", "business_impact", "scope",
})
SENTIMENT_VALUES = ("positive", "negative", "neutral")  # parser.py:241

# Keys lens.py:reconcile_batch reads off each returned object (index is the
# join key; rationale→lens_rationale, prompt_version→lens_prompt_version).
LENS_KEYS = frozenset({
    "index", "maturity_stage", "adoption_stage", "strategic_move",
    "rationale", "prompt_version",
})

# Keys analytics/strategist.py:_normalize_structured reads.
STRATEGIST_TOP_KEYS = frozenset(
    {"bottom_line", "confidence", "signals", "convergence", "scenarios", "watch"})
STRATEGIST_SIGNAL_KEYS = frozenset({
    "title", "lens", "implication", "action", "action_rationale", "impact",
    "horizon", "value_capture", "standards", "falsifier", "sources", "confidence",
})


def _json_blocks(text: str) -> list[str]:
    """All fenced ```json blocks in a prompt, in order."""
    return re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL)


def _keys_in_block(block: str) -> set[str]:
    """Object keys declared in a (possibly pseudo-)JSON block."""
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', block))


def _keys_at_depth(block: str, depth: int) -> set[str]:
    """Keys whose enclosing {}/[] nesting depth equals `depth` in a
    pseudo-JSON block (string contents are skipped so `|`/`—` don't confuse
    the scan). Depth 1 = the top-level object's own keys."""
    keys: set[str] = set()
    d, i, n = 0, 0, len(block)
    while i < n:
        ch = block[i]
        if ch in "{[":
            d += 1
        elif ch in "}]":
            d -= 1
        elif ch == '"':
            m = re.match(r'"([^"\\]*)"\s*:', block[i:])
            if m and d == depth:
                keys.add(m.group(1))
            # skip the whole string literal
            j = i + 1
            while j < n and block[j] != '"':
                j += 2 if block[j] == "\\" else 1
            i = j
        i += 1
    return keys


def _enum_from_placeholder(block: str, field: str) -> list[str] | None:
    """Parse `"field": "<a | b | c — note>"` placeholders into ['a','b','c']."""
    m = re.search(rf'"{field}"\s*:\s*"<?([^">]*)>?"', block)
    if not m:
        return None
    raw = m.group(1).split("—")[0]  # drop the trailing "— see rules" note
    vals = [v.strip().strip("`") for v in raw.split("|")]
    return [v for v in vals if v]


def _diff(name: str, what: str, declared, expected, problems: list[str]) -> None:
    declared, expected = set(declared), set(expected)
    extra, missing = declared - expected, expected - declared
    if extra:
        problems.append(f"DRIFT {name}: {what} — extra vs consumer: {sorted(extra)}")
    if missing:
        problems.append(f"DRIFT {name}: {what} — missing vs consumer: {sorted(missing)}")


def audit_extractor(path: Path, problems: list[str]) -> None:
    name = path.name
    text = path.read_text(encoding="utf-8")
    blocks = _json_blocks(text)
    if not blocks:
        problems.append(f"DRIFT {name}: no ```json block found — schema not declared")
        return
    # Block 1 = the schema template; last block = the worked example.
    schema, example = blocks[0], blocks[-1]
    _diff(name, "schema keys", _keys_in_block(schema), PARSER_KEYS, problems)
    if example is not schema:
        _diff(name, "example-item keys", _keys_in_block(example), PARSER_KEYS, problems)
        try:  # the example should itself be valid JSON with in-vocab enums
            obj = json.loads(example)
            for fld, vocab in (("sentiment", SENTIMENT_VALUES),
                               ("business_impact", _BUSINESS_IMPACT_VALUES),
                               ("scope", _SCOPE_VALUES)):
                if obj.get(fld) not in vocab:
                    problems.append(
                        f"DRIFT {name}: example {fld}={obj.get(fld)!r} not in {vocab}")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(obj.get("published_at"))):
                problems.append(
                    f"DRIFT {name}: example published_at={obj.get('published_at')!r} "
                    "is not YYYY-MM-DD")
        except json.JSONDecodeError:
            problems.append(f"DRIFT {name}: example item is not valid JSON")
    for fld, vocab in (("sentiment", SENTIMENT_VALUES),
                       ("business_impact", _BUSINESS_IMPACT_VALUES),
                       ("scope", _SCOPE_VALUES)):
        declared = _enum_from_placeholder(schema, fld)
        if declared is None:
            problems.append(f"DRIFT {name}: {fld} enum not declared in schema block")
        else:
            _diff(name, f"{fld} vocab", declared, vocab, problems)
    if "JSON array" not in text:
        problems.append(f"DRIFT {name}: prompt never demands a JSON array")


def _lens_section_values(text: str, start_pat: str, end_pat: str) -> set[str]:
    """Backticked values on `- \\`value\\` —` bullets within one lens section."""
    m = re.search(start_pat + r"(.*?)" + end_pat, text, re.DOTALL)
    if not m:
        return set()
    return set(re.findall(r"^- `([a-z/\-]+)`", m.group(1), re.MULTILINE))


def audit_lens(problems: list[str]) -> None:
    from analytics.lens import _MATURITY, _ADOPTION, _MOVE, LENS_PROMPT_VERSION

    name = "MOT_Lens_Agent.md"
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")

    blocks = _json_blocks(text)
    if blocks:
        _diff(name, "output keys", _keys_in_block(blocks[0]), LENS_KEYS, problems)
    else:
        problems.append(f"DRIFT {name}: no ```json output block found")

    for label, start, vocab, extra in (
        ("maturity_stage", r"## 1\. `maturity_stage`", _MATURITY, r"##\s*2\."),
        ("adoption_stage", r"## 2\. `adoption_stage`", _ADOPTION, r"##\s*3\."),
        ("strategic_move", r"## 3\. `strategic_move`", _MOVE, r"\n# "),
    ):
        declared = _lens_section_values(text, start, extra)
        if not declared:
            problems.append(f"DRIFT {name}: could not extract {label} vocab")
        else:
            _diff(name, f"{label} vocab", declared, vocab, problems)

    if f'"{LENS_PROMPT_VERSION}"' not in text:
        problems.append(
            f"DRIFT {name}: prompt_version literal != lens.py "
            f"LENS_PROMPT_VERSION ({LENS_PROMPT_VERSION!r})")


def _sets_from_source(path: Path, names: list[str]) -> dict[str, set]:
    """Read `NAME = {...}` set literals out of a module's source (avoids
    importing analytics.strategist, which pulls in the vector store)."""
    src = path.read_text(encoding="utf-8")
    out: dict[str, set] = {}
    for n in names:
        m = re.search(rf"^{n}\s*=\s*(\{{[^}}]*\}})", src, re.MULTILINE)
        if m:
            out[n] = set(ast.literal_eval(m.group(1)))
    return out

def audit_strategist(problems: list[str]) -> None:
    name = "Strategist_Agent.md"
    text = (PROMPTS_DIR / name).read_text(encoding="utf-8")
    # The strategist's shape block is fenced with bare ``` (not ```json).
    m = re.search(r"```(?:json)?\s*\n(\{.*?)```", text, re.DOTALL)
    if not m:
        problems.append(f"DRIFT {name}: no fenced output-shape block found")
        return
    block = m.group(1)
    _diff(name, "top-level keys", _keys_at_depth(block, 1),
          STRATEGIST_TOP_KEYS, problems)
    sig = re.search(r'"signals":\s*\[\s*(\{.*?\})\s*\]', block, re.DOTALL)
    if sig:
        keys = _keys_in_block(sig.group(1)) - {"leader", "basis", "read"}
        _diff(name, "signal keys", keys, STRATEGIST_SIGNAL_KEYS, problems)

    vocab = _sets_from_source(REPO / "analytics" / "strategist.py",
                              ["_ACTIONS", "_IMPACT", "_HORIZON", "_CONFIDENCE"])
    for fld, var in (("action", "_ACTIONS"), ("impact", "_IMPACT"),
                     ("horizon", "_HORIZON"), ("confidence", "_CONFIDENCE")):
        declared = _enum_from_placeholder(sig.group(1) if sig else block, fld)
        if declared and var in vocab:
            _diff(name, f"{fld} vocab", declared, vocab[var], problems)


def main() -> int:
    problems: list[str] = []
    for fname in EXTRACTOR_PROMPTS:
        audit_extractor(PROMPTS_DIR / fname, problems)
    audit_lens(problems)
    audit_strategist(problems)

    checked = len(EXTRACTOR_PROMPTS) + 2
    if problems:
        print(f"{len(problems)} drift finding(s) across {checked} prompts:\n")
        print("\n".join(problems))
        return 1
    print(f"OK — {checked} prompts checked (10 extractors, MOT lens, strategist): "
          "0 schema-drift mismatches vs parser/lens/strategist consumers.")
    print("(Ask_Lodestar_Agent.md returns prose — no mechanical contract to diff.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
