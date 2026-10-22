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

# A reading from the future is not a fresh reading.
FUTURE_TOLERANCE_SECONDS = 300.0

# The fields the ranking may use.
INDEX_FIELDS = (
    "intelligence_index",
    "coding_index",
    "agentic_index",
    "engineering_index",
)


# A cache is an untrusted file: only the known states and reasons of it are
# kept, and never a field that could carry something private.
CACHE_STATUSES = (
    "ok",
    "missing",
    "stale",
    "incompatible",
    "unknown_evidence_time",
    "future",
    "error",
)


def _safe_reason(value: Any) -> str:
    """A state of a cache, reduced to a known code."""
    text = str(value or "").strip().lower()
    if text in CACHE_STATUSES:
        return text
    if text in (codes.MISSING_CREDENTIALS, codes.STALE_READING, codes.INVALID_RESPONSE):
        return text
    return codes.UNKNOWN


def _safe_text(value: Any) -> str | None:
    """A timestamp of a cache, and nothing else.

    A cache is an untrusted file, so only a value that really is a timestamp
    is kept. A field that carries an address, a path, or a credential is
    dropped instead of trimmed.
    """
    import re

    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", text):
        return None
    return text


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
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return missing
    if not isinstance(document, Mapping):
        return missing
    fetched = _finite(document.get("fetched_at_epoch"))
    if fetched is None:
        # A cache without a finite moment it was read cannot be aged, so it
        # cannot be fresh. A NaN or an infinity lands here too, so an
        # untrusted file never raises in the middle of a collection.
        return {**missing, "status": "unknown_evidence_time"}
    moment_value = _finite(moment)
    if moment_value is None:
        return {**missing, "status": "unknown_evidence_time"}
    if fetched > moment_value + FUTURE_TOLERANCE_SECONDS:
        # A reading from the future is not a fresh reading.
        return {**missing, "status": "future", "fetched_at_epoch": fetched}
    age = moment_value - fetched
    version = str(document.get("intelligence_index_version") or "").strip()
    if not version:
        # A cache without the version of its scores cannot be compared with
        # another one, so it is not usable.
        return {
            **missing,
            "status": "incompatible",
            "reason": codes.INVALID_RESPONSE,
            "index_version": "",
        }
    records = document.get("records")
    if not isinstance(records, list):
        return missing
    if age > MAX_CACHE_AGE_SECONDS:
        return {
            **missing,
            "status": "stale",
            "reason": codes.STALE_READING,
            "fetched_at": _safe_text(document.get("fetched_at")),
            "fetched_at_epoch": fetched,
            "age_seconds": int(age),
        }
    return {
        "status": "ok",
        "reason": codes.OK,
        "index_version": version,
        "fetched_at": _safe_text(document.get("fetched_at")),
        "fetched_at_epoch": fetched,
        "age_seconds": int(age),
        "records": [record for record in records if isinstance(record, Mapping)],
    }


def _indices(record: Mapping[str, Any]) -> dict[str, float]:
    """The indices of a record, nested or flat."""
    values: dict[str, float] = {}
    nested = record.get("indices")
    for field in INDEX_FIELDS:
        value = _finite(record.get(field))
        if value is None and isinstance(nested, Mapping):
            value = _finite(nested.get(field))
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


# The statuses a normalization can end with. A rejected snapshot keeps one of
# these, and never a raw field of the file.
NORMALIZE_FREE_TIER = "free"


def _read_time(value: Any) -> tuple[str | None, float | None]:
    """The read time of a snapshot, as text and as epoch seconds."""
    text = _safe_text(value)
    if text is None:
        return None, None
    from datetime import datetime, timezone

    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return text, moment.timestamp()


def _record(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """One official record, in the cache contract.

    A missing or null value is preserved as None: a score that was not
    measured is not zero, and a price that was not published is not free.
    """
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return None
    evaluations = entry.get("evaluations") if isinstance(entry.get("evaluations"), Mapping) else {}
    pricing = entry.get("pricing") if isinstance(entry.get("pricing"), Mapping) else {}
    performance = entry.get("performance") if isinstance(entry.get("performance"), Mapping) else {}
    creator = entry.get("model_creator") if isinstance(entry.get("model_creator"), Mapping) else {}
    cost = entry.get("artificial_analysis_intelligence_index_cost")
    cost_per_task = None
    if isinstance(cost, Mapping):
        per_task = cost.get("cost_per_task")
        if isinstance(per_task, Mapping):
            cost_per_task = _finite(per_task.get("total_cost"))
        if cost_per_task is None:
            cost_per_task = _finite(cost.get("total_cost"))
    return {
        "model": name,
        "slug": str(entry.get("slug") or name),
        "id": str(entry.get("id") or ""),
        "provider": str(creator.get("name") or ""),
        "release_date": entry.get("release_date") if isinstance(entry.get("release_date"), str) else None,
        "indices": {
            "intelligence_index": _finite(evaluations.get("artificial_analysis_intelligence_index")),
            "coding_index": _finite(evaluations.get("artificial_analysis_coding_index")),
            "agentic_index": _finite(evaluations.get("artificial_analysis_agentic_index")),
            "engineering_index": _finite(evaluations.get("artificial_analysis_engineering_index")),
        },
        "prices": {
            "input": _finite(pricing.get("price_1m_input_tokens")),
            "output": _finite(pricing.get("price_1m_output_tokens")),
            "cache_read": _finite(pricing.get("price_1m_cache_hit_tokens")),
            "cache_write": _finite(pricing.get("price_1m_cache_write_tokens")),
        },
        "cost_per_task": cost_per_task,
        "median_performance": _finite(performance.get("median_output_tokens_per_second")),
        "median_time_to_first_token_seconds": _finite(
            performance.get("median_time_to_first_token_seconds")
        ),
    }


def normalize(snapshot: Any, now: float | None = None) -> dict[str, Any]:
    """Normalize one whole client snapshot into the cache contract.

    The snapshot is accepted only when it is the free tier, complete, over
    every page, with one page size and one total, one version, a finite
    actual read time that is not in the future, and as many records as it
    says. Anything else is rejected with a bounded status: a partial walk is
    never promoted to a ranking snapshot.
    """
    moment = time.time() if now is None else now
    rejection = {"status": "rejected", "reason": "", "records": []}
    body = snapshot.get("results") if isinstance(snapshot, Mapping) and isinstance(snapshot.get("results"), Mapping) else snapshot
    if not isinstance(body, Mapping):
        return {**rejection, "reason": "not_a_snapshot"}
    tier = str(body.get("tier") or "")
    if tier != NORMALIZE_FREE_TIER:
        return {**rejection, "reason": "not_the_free_tier"}
    version = str(body.get("intelligence_index_version") or "").strip()
    if not version:
        return {**rejection, "reason": "no_index_version"}
    completeness = body.get("completeness") if isinstance(body.get("completeness"), Mapping) else {}
    if completeness.get("scope") != "all" or completeness.get("complete") is not True:
        return {**rejection, "reason": "incomplete"}
    if completeness.get("requested_first_page") != 1:
        return {**rejection, "reason": "not_from_the_first_page"}
    if completeness.get("last_page_has_more") is not False:
        return {**rejection, "reason": "last_page_still_has_more"}
    total_pages = completeness.get("total_pages")
    fetched = completeness.get("pages_fetched")
    if not isinstance(total_pages, int) or isinstance(total_pages, bool) or total_pages < 1:
        return {**rejection, "reason": "no_total_pages"}
    if fetched != total_pages:
        return {**rejection, "reason": "pages_disagree"}
    records = body.get("data")
    if not isinstance(records, list) or len(records) != completeness.get("records"):
        return {**rejection, "reason": "record_count_disagrees"}
    pages = body.get("pages")
    if not isinstance(pages, list) or len(pages) != total_pages:
        return {**rejection, "reason": "pages_disagree"}
    page_size = completeness.get("page_size")
    seen: set[int] = set()
    for page in pages:
        if not isinstance(page, Mapping):
            return {**rejection, "reason": "pages_disagree"}
        number = page.get("page")
        if not isinstance(number, int) or isinstance(number, bool) or number in seen:
            return {**rejection, "reason": "pages_disagree"}
        seen.add(number)
        if page.get("total_pages") != total_pages or page.get("page_size") != page_size:
            return {**rejection, "reason": "pages_disagree"}
    if seen != set(range(1, total_pages + 1)):
        return {**rejection, "reason": "pages_disagree"}
    evidence = body.get("evidence") if isinstance(body.get("evidence"), Mapping) else {}
    if str(evidence.get("source") or "") != "live" or str((snapshot or {}).get("meta", {}).get("source") or "") not in ("", "live"):
        return {**rejection, "reason": "not_a_live_read"}
    read_at, read_epoch = _read_time(evidence.get("read_at"))
    if read_at is None or read_epoch is None:
        return {**rejection, "reason": "no_read_time"}
    if read_epoch > moment + FUTURE_TOLERANCE_SECONDS:
        return {**rejection, "reason": "read_time_in_the_future"}
    normalized: list[dict[str, Any]] = []
    for entry in records:
        if not isinstance(entry, Mapping):
            continue
        record = _record(entry)
        if record is None:
            return {**rejection, "reason": "a_record_has_no_name"}
        normalized.append(record)
    if len(normalized) != completeness.get("records"):
        return {**rejection, "reason": "record_count_disagrees"}
    return {
        "status": "ok",
        "reason": codes.OK,
        "intelligence_index_version": version,
        "tier": tier,
        "fetched_at": read_at,
        "fetched_at_epoch": read_epoch,
        "source": "artificialanalysis",
        "attribution": _safe_text(evidence.get("attribution")) or "",
        "completeness": {
            "scope": "all",
            "complete": True,
            "pages_fetched": fetched,
            "total_pages": total_pages,
            "page_size": page_size,
            "records": completeness.get("records"),
        },
        "records": normalized,
    }


def write_cache(path: str | os.PathLike[str], document: Mapping[str, Any]) -> bool:
    """Write the cache atomically, and say whether it changed.

    A snapshot whose bytes are already the file leaves the file untouched, so
    a refresh that found nothing new does not rewrite the read time of the
    cached evidence.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=1, sort_keys=True, allow_nan=False) + "\n"
    try:
        if target.read_text(encoding="utf-8") == payload:
            return False
    except OSError:
        pass
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(payload, encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)
    return True


def main(argv: list[str] | None = None) -> int:
    """Normalize one whole client snapshot into the cache contract."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="aa.py",
        description="Normalize an Artificial Analysis client snapshot into the cache.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    normalize_command = commands.add_parser("normalize")
    normalize_command.add_argument("--input", required=True, help="The client snapshot.")
    normalize_command.add_argument("--output", required=True, help="The cache to write.")
    normalize_command.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        document = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(json.dumps({"status": "rejected", "reason": "unreadable_input"}))
        return 2
    normalized = normalize(document)
    if normalized.get("status") != "ok":
        print(json.dumps({"status": normalized.get("status"), "reason": normalized.get("reason")}))
        return 2
    changed = False
    if not args.dry_run:
        changed = write_cache(args.output, normalized)
    print(
        json.dumps(
            {
                "status": "ok",
                "reason": normalized.get("reason"),
                "version": normalized.get("intelligence_index_version"),
                "records": len(normalized.get("records") or []),
                "pages": normalized.get("completeness", {}).get("pages_fetched"),
                "read_at": normalized.get("fetched_at"),
                "written": changed,
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - the CLI entry point
    raise SystemExit(main())


def _normalise(name: str) -> str:
    """The name without its separators, so a feed and a provider agree."""
    return "".join(character for character in str(name or "").lower() if character.isalnum())


def lookup(cache: Mapping[str, Any], model: str) -> dict[str, Any] | None:
    """The feed record of one model, when the cache binds it exactly.

    The binding is exact. A record whose name only contains the name of the
    model, or only starts with it, is a different model or a different
    reasoning variant, and an ambiguous match returns nothing: a model never
    inherits the score of another one.
    """
    if not cache or cache.get("status") != "ok":
        return None
    text = _normalise(model)
    if not text:
        return None
    matches = [
        record
        for record in (cache.get("records") or [])
        if isinstance(record, Mapping)
        and isinstance(record.get("model"), str)
        and _normalise(record["model"]) == text
    ]
    if len(matches) != 1:
        # No record, or more than one: the model is unknown, not scored. A
        # prefix match would let a reasoning variant inherit the score of
        # another model.
        return None
    for record in matches:
        name = record.get("model")
        if not isinstance(name, str):
            continue
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
