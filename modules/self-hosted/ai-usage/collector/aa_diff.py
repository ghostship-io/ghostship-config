"""The diff of two Artificial Analysis snapshots: what changed.

The pull runs once a day. When a model is new, or when a measurement of a
model changed, the ranking has to look at it again. This module says what
changed between two pulls, so the producer can publish the change and the
ranking can be refreshed.

The diff is informational: it never decides anything. It names the models
that are new, the models that are gone and the models whose measurements
changed, and it says which field changed.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

# The numeric fields the diff watches, and the tolerance of each. A number
# that moved less than its tolerance is not a change.
NUMERIC_FIELDS: dict[str, float] = {
    "intelligence_index": 1e-9,
    "cost_per_task": 1e-9,
    "price_1m_input": 1e-12,
    "price_1m_output": 1e-12,
    "aa3d_elo": 1e-6,
    "median_output_tokens_per_second": 1e-6,
}

# The text fields the diff watches.
TEXT_FIELDS = (
    "name",
    "creator",
    "reasoning_condition",
    "release_date",
    "deprecated",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _changed(old: Any, new: Any, tolerance: float) -> bool:
    """True when a number changed by more than its tolerance."""
    left = _number(old)
    right = _number(new)
    if left is None and right is None:
        return False
    if left is None or right is None:
        return True
    return not math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _record_of(entry: Any) -> dict[str, Any]:
    """The fields of one record the diff watches."""
    if not isinstance(entry, Mapping):
        return {}
    prices = entry.get("prices") if isinstance(entry.get("prices"), Mapping) else {}
    return {
        "name": str(entry.get("model") or entry.get("name") or ""),
        "creator": str(entry.get("provider") or entry.get("creator") or ""),
        "reasoning_condition": str(entry.get("reasoning_condition") or ""),
        "release_date": str(entry.get("release_date") or ""),
        "deprecated": bool(entry.get("deprecated")),
        "intelligence_index": _number(
            (entry.get("indices") or {}).get("intelligence_index")
            if isinstance(entry.get("indices"), Mapping)
            else entry.get("intelligence_index")
        ),
        "cost_per_task": _number(entry.get("cost_per_task")),
        "price_1m_input": _number(prices.get("input")),
        "price_1m_output": _number(prices.get("output")),
        "aa3d_elo": _number(entry.get("aa3d_elo")),
        "median_output_tokens_per_second": _number(
            entry.get("median_performance")
        ),
    }


def _index(records: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """The records of a snapshot, by slug."""
    found: dict[str, dict[str, Any]] = {}
    for entry in records or ():
        if not isinstance(entry, Mapping):
            continue
        slug = str(entry.get("slug") or "")
        if not slug:
            continue
        found[slug] = _record_of(entry)
    return found


def diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    """The difference between two pulled snapshots.

    The result says which models are new, which are gone, and which
    measurements changed. It is the trigger for a re-ranking, not the
    re-ranking itself.
    """
    old_index = _index(old.get("records") or ())
    new_index = _index(new.get("records") or ())
    added = sorted(set(new_index) - set(old_index))
    removed = sorted(set(old_index) - set(new_index))
    changed: dict[str, dict[str, Any]] = {}
    for slug in sorted(set(old_index) & set(new_index)):
        before = old_index[slug]
        after = new_index[slug]
        differences: dict[str, Any] = {}
        for field, tolerance in NUMERIC_FIELDS.items():
            if _changed(before.get(field), after.get(field), tolerance):
                differences[field] = {"old": before.get(field), "new": after.get(field)}
        for field in TEXT_FIELDS:
            if before.get(field) != after.get(field):
                differences[field] = {"old": before.get(field), "new": after.get(field)}
        if differences:
            changed[slug] = {
                "name": after.get("name") or before.get("name") or "",
                "differences": differences,
            }
    return {
        "old_fetched_at": old.get("fetched_at"),
        "new_fetched_at": new.get("fetched_at"),
        "old_count": len(old_index),
        "new_count": len(new_index),
        "added": [
            {
                "slug": slug,
                "name": new_index[slug].get("name") or "",
                "creator": new_index[slug].get("creator") or "",
                "intelligence_index": new_index[slug].get("intelligence_index"),
                "cost_per_task": new_index[slug].get("cost_per_task"),
                "release_date": new_index[slug].get("release_date"),
                "reasoning_condition": new_index[slug].get("reasoning_condition"),
            }
            for slug in added
        ],
        "removed": [
            {
                "slug": slug,
                "name": old_index[slug].get("name") or "",
                "creator": old_index[slug].get("creator") or "",
                "intelligence_index": old_index[slug].get("intelligence_index"),
            }
            for slug in removed
        ],
        "changed": changed,
        "has_new_models": bool(added),
        "has_changed_models": bool(changed),
    }


def load(path: str | Path) -> dict[str, Any]:
    """Read a pulled snapshot."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}
