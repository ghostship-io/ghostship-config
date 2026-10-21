"""The Artificial Analysis quality feed, as a cached source.

Artificial Analysis publishes a free API with the headline intelligence,
coding, agentic, and engineering indices of a model, its release date, its
token prices, its cost per task, and its median performance:

    GET https://artificialanalysis.ai/api/v2/language/models/free
    ?page=1&page_size=100

The response is paginated (`has_more`, `total_pages`). A key is required and
the free tier allows a hundred requests in twenty four hours, so the feed is
read once a day by the daily procedure and cached. The collector only ever
reads that cache: it never calls the feed, so the request budget belongs to
one place.

The client is deliberately careful about what it claims:

* The prices in the feed are the prices of the feed, for the models the feed
  lists. A benchmark cost per task is not a token price and is never used as
  one.
* The intelligence index has a version. A record of a different version is
  not mixed with the current one.
* A model the feed does not list is unknown, not bad. No score is invented.
* Without a cache the feed is simply absent, and the coverage is reported as
  a gap.

The credential and the fetch belong to the service library, which owns the
clients of the APIs the fleet uses. This module is the consumer side.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

import codes

# The version of the intelligence index this collector understands. A cache
# of a different version is not merged with it.
INTELLIGENCE_INDEX_VERSION = "4.3"

# A cache older than this is stale. The daily procedure reads the feed once
# a day, so a day and a half is a generous bound.
MAX_CACHE_AGE_SECONDS = 36 * 3600.0

# The fields the ranking may use.
INDEX_FIELDS = (
    "intelligence_index",
    "coding_index",
    "agentic_index",
    "engineering_index",
)


def _finite(value: Any) -> float | None:
    """A finite float, or None. A NaN or an infinity is never published."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def load_cache(path: str | os.PathLike[str], now: float | None = None) -> dict[str, Any]:
    """Read the cached feed.

    The result always says what it is: the records, the index version, the
    time of the read, and the status. A missing or stale cache is a coverage
    gap, never an empty quality.
    """
    moment = time.time() if now is None else now
    missing = {
        "status": "missing",
        "reason": codes.MISSING_CREDENTIALS,
        "index_version": INTELLIGENCE_INDEX_VERSION,
        "fetched_at": None,
        "fetched_at_epoch": None,
        "age_seconds": None,
        "records": [],
    }
    try:
        stat = os.stat(path)
    except OSError:
        return missing
    age = max(0.0, moment - stat.st_mtime)
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return missing
    if not isinstance(document, Mapping):
        return missing
    version = str(document.get("intelligence_index_version") or "")
    if version != INTELLIGENCE_INDEX_VERSION:
        # A different index version is not mixed with the current one.
        return {
            **missing,
            "status": "incompatible",
            "reason": codes.INVALID_RESPONSE,
            "index_version": version,
        }
    records = document.get("records")
    if not isinstance(records, list):
        return missing
    if age > MAX_CACHE_AGE_SECONDS:
        return {
            **missing,
            "status": "stale",
            "reason": codes.STALE_READING,
            "fetched_at": document.get("fetched_at"),
            "fetched_at_epoch": document.get("fetched_at_epoch"),
            "age_seconds": int(age),
        }
    return {
        "status": "ok",
        "reason": codes.OK,
        "index_version": version,
        "fetched_at": document.get("fetched_at"),
        "fetched_at_epoch": document.get("fetched_at_epoch"),
        "age_seconds": int(age),
        "records": [record for record in records if isinstance(record, Mapping)],
    }


def _indices(record: Mapping[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for field in INDEX_FIELDS:
        value = _finite(record.get(field))
        if value is not None:
            values[field] = value
    return values


def _prices(record: Mapping[str, Any]) -> dict[str, float]:
    prices = record.get("prices")
    if not isinstance(prices, Mapping):
        return {}
    result: dict[str, float] = {}
    for source, target in (
        ("input", "input"),
        ("output", "output"),
        ("cache_read", "cache_read"),
    ):
        value = _finite(prices.get(source))
        if value is not None:
            result[target] = value
    return result


def _cost_per_task(record: Mapping[str, Any]) -> float | None:
    """The cost per task of one feed record, when the feed reports it."""
    value = record.get("cost_per_task")
    if isinstance(value, Mapping):
        value = value.get("total_cost")
    return _finite(value)


def _median_performance(record: Mapping[str, Any]) -> float | None:
    """The median performance (the speed) of one feed record."""
    value = record.get("median_performance")
    if isinstance(value, Mapping):
        value = value.get("median")
    return _finite(value)


def _normalise(name: str) -> str:
    """The name without its separators, so a feed and a provider agree."""
    return "".join(character for character in str(name or "").lower() if character.isalnum())


def lookup(cache: Mapping[str, Any], model: str) -> dict[str, Any] | None:
    """The feed record of one model, when the cache knows it."""
    if not cache or cache.get("status") != "ok":
        return None
    text = _normalise(model)
    for record in cache.get("records") or []:
        if not isinstance(record, Mapping):
            continue
        name = record.get("model")
        if not isinstance(name, str) or not name:
            continue
        lowered = _normalise(name)
        if lowered and (lowered == text or lowered in text or text.endswith(lowered)):
            return {
                "model": name,
                "provider": str(record.get("provider") or ""),
                "release_date": record.get("release_date"),
                "indices": _indices(record),
                "prices": _prices(record),
                "cost_per_task": _cost_per_task(record),
                "median_performance": _median_performance(record),
                "index_version": cache.get("index_version"),
                "fetched_at": cache.get("fetched_at"),
                "source": "artificialanalysis",
            }
    return None
