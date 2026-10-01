"""
Gold-label set — schema, loader, and validator for the hand-labelled articles the
eval harness scores against (backend/eval/gold_labels.jsonl).

A gold label is one article (keyed by `url`) with a human's *true* MOT classification
for any subset of four fields. Leaving a field null means "not labelled — don't score
it", so a labeller can label only the fields they're confident about.

The allowed value vocabularies are imported from the pipeline itself (the lens and the
parser) rather than redefined here — there must be exactly one source of truth, or the
gold set and the pipeline could silently diverge on what e.g. a valid scope is.

All functions are pure (no I/O beyond reading the given path).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

# Canonical label vocabularies — single source of truth. `_MATURITY`/`_ADOPTION`
# are the lens's stage sets; `_BUSINESS_IMPACT_VALUES`/`_SCOPE_VALUES` are the
# parser's. Imported (not duplicated) so the gold set can never drift from them.
from analytics.lens import _MATURITY, _ADOPTION
from home_news.parser import _BUSINESS_IMPACT_VALUES, _SCOPE_VALUES

# The fields a gold label may carry, each scored against the matching pipeline output.
GOLD_FIELDS: tuple[str, ...] = ("maturity_stage", "adoption_stage", "business_impact", "scope")

ALLOWED: dict[str, frozenset] = {
    "maturity_stage": frozenset(_MATURITY),
    "adoption_stage": frozenset(_ADOPTION),
    "business_impact": frozenset(_BUSINESS_IMPACT_VALUES),
    "scope": frozenset(_SCOPE_VALUES),
}


def normalize_label(value) -> Optional[str]:
    """Normalise a raw label to match the pipeline's own normalisation
    (`lens._pick` / `parser`): lowercase, stripped, underscores→hyphens. Returns
    None for empty/missing so an unlabelled field is simply not scored. Pure."""
    if value is None:
        return None
    v = str(value).strip().lower().replace("_", "-")
    return v or None


@dataclass
class GoldLabel:
    """One hand-labelled article. `url` is the join key against the feed tables.
    Each of the four label fields is optional — None means "not labelled"."""
    url: str
    maturity_stage: Optional[str] = None
    adoption_stage: Optional[str] = None
    business_impact: Optional[str] = None
    scope: Optional[str] = None
    feed: Optional[str] = None     # feed key the article belongs to (context only)
    notes: Optional[str] = None    # labeller's rationale (optional, not scored)

    @property
    def labelled_fields(self) -> dict[str, str]:
        """The subset of GOLD_FIELDS this row actually labelled (non-null)."""
        return {f: getattr(self, f) for f in GOLD_FIELDS if getattr(self, f) is not None}


def label_from_dict(obj: dict) -> GoldLabel:
    """Build a normalised GoldLabel from a raw JSON object. Pure — does not
    validate values against ALLOWED (use `validate` for that)."""
    return GoldLabel(
        url=str(obj.get("url") or "").strip(),
        maturity_stage=normalize_label(obj.get("maturity_stage")),
        adoption_stage=normalize_label(obj.get("adoption_stage")),
        business_impact=normalize_label(obj.get("business_impact")),
        scope=normalize_label(obj.get("scope")),
        feed=(str(obj.get("feed")).strip() if obj.get("feed") else None),
        notes=(str(obj.get("notes")).strip() if obj.get("notes") else None),
    )


def read_jsonl(path: str | Path) -> Iterator[dict]:
    """Yield the JSON object on each non-blank line of a JSONL file. Raises
    ValueError (with the line number) on malformed JSON or a non-object line, so a
    typo fails loud rather than silently dropping a row. Shared by the gold loader
    and the prediction-fixture loader so they parse identically."""
    text = Path(path).read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{lineno}: invalid JSON — {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{lineno}: expected a JSON object, got {type(obj).__name__}")
        yield obj


def load_gold(path: str | Path) -> list[GoldLabel]:
    """Load + normalise gold labels from a JSONL file (one JSON object per line)."""
    return [label_from_dict(obj) for obj in read_jsonl(path)]


def validate(labels: Iterable[GoldLabel]) -> list[str]:
    """Return a list of human-readable problems with the gold set (empty == clean).
    Run this while labelling to catch typos before they corrupt the scorecard:
      - missing/empty url
      - a field value outside its allowed vocabulary
      - a row that labels nothing (no scorable field)
      - a duplicate url (later rows would shadow earlier ones)
    Pure."""
    problems: list[str] = []
    seen: set[str] = set()
    for i, lab in enumerate(labels):
        where = f"row {i} (url={lab.url!r})"
        if not lab.url:
            problems.append(f"{where}: missing url")
        elif lab.url in seen:
            problems.append(f"{where}: duplicate url")
        else:
            seen.add(lab.url)

        labelled = lab.labelled_fields
        if not labelled:
            problems.append(f"{where}: no labelled fields — nothing to score")
        for field, value in labelled.items():
            if value not in ALLOWED[field]:
                allowed = ", ".join(sorted(ALLOWED[field]))
                problems.append(f"{where}: {field}={value!r} not in {{{allowed}}}")
    return problems
