"""The measured Artificial Analysis 3D feed: Elo for interactive 3D scenes.

The 3D tier ranks a measured AA-3D Elo and nothing else. The feed is a
separate, bounded file: a snapshot of Artificial Analysis' own AA-3D
evaluation, with the Elo, the source, the date and the benchmark conditions of
every record. A model the feed has not measured has no 3D rank, and its
general intelligence index is never used as a 3D score.

This module only reads the file. It opens no socket, starts no poller and
holds no credential: the root acquires the public source through the existing
client and drops the snapshot where the argument points. The reader validates
strictly, so a malformed row is a refusal, not a zero.

The evaluation is interactive Three.js scenes, not a CAD or printable-geometry
test; the record carries that condition so a consumer can see what the Elo
measures.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import aa_bind

# A 3D Elo older than this is not usable evidence of the current model.
MAX_AGE_SECONDS = 30 * 24 * 3600.0


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _iso_epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _finite(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _record(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """One validated AA-3D record, or None when it is not usable evidence.

    The fields are allowlisted: the measurement name, the Elo, its interval,
    the rank, the anchor flag and the AA-3D cost. No arbitrary id, slug,
    source, release date, normalization or free text is read from the file.
    """
    model = str(raw.get("model") or "").strip()
    if not model or len(model) > 120:
        return None
    elo = _finite(raw.get("elo"))
    if elo is None or elo < 0.0:
        return None
    rank = _finite(raw.get("rank"))
    if rank is None or rank < 1.0 or rank != int(rank):
        return None
    if rank > MAX_RECORDS:
        return None
    rank_range = str(raw.get("rank_range") or "")[:16] or None
    if rank_range is not None and not re.fullmatch(r"[0-9-]{1,16}", rank_range):
        return None
    low = _finite(raw.get("ci95_low"))
    high = _finite(raw.get("ci95_high"))
    if (low is None) != (high is None):
        return None
    if low is not None and (low > elo or high < elo):
        # The interval must contain the point estimate.
        return None
    raw_cost = raw.get("cost_per_task")
    cost = _finite(raw_cost)
    if raw_cost is not None and (cost is None or cost < 0.0):
        return None
    return {
        "model": model,
        "elo": round(elo, 1),
        "elo_interval": {
            "low": None if low is None else round(low, 1),
            "high": None if high is None else round(high, 1),
        },
        "rank": int(rank),
        "rank_range": rank_range,
        "anchor": bool(raw.get("anchor", False)),
        "cost_per_task": None if cost is None else round(cost, 6),
        # Published only after the loader applies the board policy.
        "normalized": None,
        "source_normalized": False,
        "conditions": {"benchmark": BENCHMARK, "scope": PUBLIC_CONDITION},
        "source": SOURCE_URL,
    }


def _normalization(raw: Any) -> dict[str, Any] | None:
    """The source's own explicit Elo normalization, or None.

    An Elo is not a 0..100 index, and the collector does not invent an anchor.
    The feed may publish the normalization it uses; without it the normalized
    capability is unknown and no combined 3D value is computed.
    """
    if not isinstance(raw, Mapping):
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    if kind == "min-max":
        floor = _finite(raw.get("floor"))
        ceiling = _finite(raw.get("ceiling"))
        if floor is None or ceiling is None or ceiling <= floor:
            return None
        return {"kind": "min-max", "floor": floor, "ceiling": ceiling}
    if kind == "linear":
        offset = _finite(raw.get("offset"))
        scale = _finite(raw.get("scale"))
        if offset is None or scale is None or scale == 0.0:
            return None
        return {"kind": "linear", "offset": offset, "scale": scale}
    return None


def normalize(elo: float | None, normalization: Mapping[str, Any] | None) -> float | None:
    """The normalized 0..1 capability, using only the published transform."""
    if not isinstance(elo, (int, float)) or isinstance(elo, bool):
        return None
    if not isinstance(normalization, Mapping):
        return None
    if "min_elo" in normalization and "max_elo" in normalization:
        floor = normalization.get("min_elo")
        ceiling = normalization.get("max_elo")
        if not isinstance(floor, (int, float)) or not isinstance(ceiling, (int, float)):
            return None
        if ceiling <= floor:
            # Every measured Elo is equal: every model has the same relative
            # performance, and the cost breaks the tie.
            return 1.0
        return max(0.0, min(1.0, (float(elo) - float(floor)) / (float(ceiling) - float(floor))))
    kind = normalization.get("kind")
    if kind == "min-max":
        floor = normalization.get("floor")
        ceiling = normalization.get("ceiling")
        if not isinstance(floor, (int, float)) or not isinstance(ceiling, (int, float)):
            return None
        if ceiling <= floor:
            return None
        return max(0.0, min(1.0, (float(elo) - float(floor)) / (float(ceiling) - float(floor))))
    if kind == "linear":
        offset = normalization.get("offset")
        scale = normalization.get("scale")
        if not isinstance(offset, (int, float)) or not isinstance(scale, (int, float)) or scale == 0.0:
            return None
        return max(0.0, min(1.0, (float(elo) + float(offset)) / float(scale)))
    return None


SOURCE_URL = "https://artificialanalysis.ai/evaluations/aa-3d"
SCHEMA = "ghostship.aa3d.evidence"
BENCHMARK = "AA-3D"
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 256
MAX_FUTURE_SECONDS = 300.0
PUBLIC_CONDITION = (
    "AA-3D evaluates interactive Three.js 3D scenes; it is not CAD or "
    "printable-geometry suitability"
)


def _rejected(reason: str) -> dict[str, Any]:
    """A whole-snapshot refusal. Never a partial board."""
    return {
        "status": "invalid",
        "reason": reason,
        "source": SOURCE_URL,
        "source_url": SOURCE_URL,
        "benchmark": BENCHMARK,
        "benchmark_version": None,
        "attribution": None,
        "completeness": None,
        "bounds": None,
        "fingerprint": None,
        "normalization": None,
        "records": [],
    }


def _bounded_read(path: str) -> str | None:
    """Read at most MAX_BYTES, and refuse a larger file instead of slicing."""
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def load_cache(path: str | None, now: float) -> dict[str, Any] | None:
    """The validated AA-3D snapshot, or None when it is absent.

    The whole snapshot is accepted or refused: a truncated board, a duplicate
    or missing record, a bad cost, interval or rank, a future or non-finite
    time, a foreign source or an incomplete scope is an `invalid` snapshot,
    never a rebased subset. The fields are allowlisted, and the published
    source and conditions are the fixed public ones, not whatever the file
    says.
    """
    if not path:
        return None
    raw = _bounded_read(str(path))
    if raw is None:
        return None
    try:
        document = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(document, Mapping):
        return None
    if document.get("schema") != SCHEMA or document.get("schema_version") != 1:
        return _rejected("unexpected schema")
    if document.get("benchmark") != BENCHMARK:
        return _rejected("unexpected benchmark")
    version = str(document.get("benchmark_version") or "").strip()
    if not version:
        return _rejected("missing benchmark version")
    if str(document.get("source_url") or "").strip() != SOURCE_URL:
        return _rejected("unexpected source url")
    completeness = document.get("completeness")
    raw_records = document.get("records")
    if not isinstance(completeness, Mapping) or completeness.get("complete") is not True:
        return _rejected("incomplete snapshot")
    if str(completeness.get("scope") or "") != "entire_displayed_leaderboard":
        return _rejected("unexpected scope")
    if not isinstance(raw_records, list) or not raw_records:
        return _rejected("no records")
    if len(raw_records) > MAX_RECORDS:
        return _rejected("too many records")
    if not isinstance(completeness.get("records"), int) or completeness.get(
        "records"
    ) != len(raw_records):
        return _rejected("record count does not match the declared board")
    observed = _iso_epoch(document.get("observed_at"))
    if observed is None or not math.isfinite(observed):
        return _rejected("missing observation time")
    if observed > float(now) + MAX_FUTURE_SECONDS:
        return _rejected("observation time is in the future")
    age = max(0.0, float(now) - observed)
    if age > MAX_AGE_SECONDS:
        return _rejected("snapshot is older than the feed age")

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            return _rejected("malformed record")
        record = _record(raw_record)
        if record is None:
            return _rejected("malformed record")
        key = record["model"].strip().lower()
        if key in seen:
            return _rejected("duplicate measurement")
        seen.add(key)
        # The published source and condition are the fixed public ones; no
        # arbitrary condition key or private URL is forwarded.
        record["source"] = SOURCE_URL
        record["conditions"] = {"benchmark": BENCHMARK, "scope": PUBLIC_CONDITION}
        records.append(record)
    if len(records) != len(raw_records):
        return _rejected("record was dropped")
    if sorted(record["rank"] for record in records) != list(range(1, len(records) + 1)):
        # The board is a complete, ordered leaderboard: finite, unique,
        # sequential ranks with no duplicate or gap.
        return _rejected("ranks are not the complete sequence")

    elos = [float(record["elo"]) for record in records]
    bounds = {
        "min_elo": min(elos),
        "max_elo": max(elos),
        "count": len(elos),
    }
    for record in records:
        record["normalized"] = normalize(record["elo"], bounds)
        record["source_normalized"] = False
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "schema": SCHEMA,
                "benchmark": BENCHMARK,
                "benchmark_version": version,
                "source_url": SOURCE_URL,
                "observed_at": document.get("observed_at"),
                "board": [[record["model"], record["elo"]] for record in records],
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "status": "ok",
        "reason": "",
        "source": SOURCE_URL,
        "source_url": SOURCE_URL,
        "benchmark": BENCHMARK,
        "benchmark_version": version[:20],
        "attribution": "Artificial Analysis (https://artificialanalysis.ai/)",
        "completeness": {
            "complete": True,
            "records": len(records),
            "scope": "entire_displayed_leaderboard",
        },
        "bounds": bounds,
        "fingerprint": fingerprint,
        "normalization": {
            "kind": "relative-minmax",
            "policy": (
                "(elo - min board elo) / (max board elo - min board elo) over "
                "the complete snapshot before any exclusion; all equal means 1"
            ),
            "bounds": bounds,
            "fingerprint": fingerprint,
            "not": "a win probability, an AA intelligence index or a zero-ability claim",
        },
        "fetched_at": datetime.fromtimestamp(observed, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "fetched_at_epoch": observed,
        "age_seconds": round(age, 1),
        "records": records,
    }


def lookup(cache: Mapping[str, Any] | None, provider: str, model: str) -> dict[str, Any]:
    """The AA-3D record of one model, or the reason it has none."""
    if not isinstance(cache, Mapping) or cache.get("status") != "ok":
        return {
            "state": "missing" if not cache or cache.get("status") == "missing" else str((cache or {}).get("status") or "missing"),
            "reason": "no usable AA-3D snapshot",
        }
    binding = aa_bind.resolve(cache.get("records") or (), provider, model)
    if binding.get("state") != "measured":
        return {
            "state": "missing",
            "reason": str(binding.get("reason") or "no AA-3D record for this model"),
        }
    record = binding["record"]
    normalization = cache.get("normalization")
    normalised = record.get("normalized")
    if normalised is None:
        normalised = normalize(record.get("elo"), normalization)
    return {
        "state": "measured",
        "elo": record.get("elo"),
        "elo_interval": record.get("elo_interval") or {},
        "cost_per_task": record.get("cost_per_task"),
        "normalized": normalised,
        "normalization": normalization,
        "normalization_state": (
            "source"
            if record.get("source_normalized")
            else ("relative-minmax" if normalised is not None else "unknown")
        ),
        "bounds": cache.get("bounds"),
        "fingerprint": cache.get("fingerprint"),
        "source": record.get("source"),
        "benchmark": str(cache.get("benchmark") or "aa-3d"),
        "conditions": record.get("conditions") or {},
        "observed_at": record.get("observed_at"),
        "released_at": None,
        "task_count": record.get("task_count"),
        "aa_id": None,
        "aa_slug": None,
        "aa_name": record.get("model"),
        "note": (
            "an AA-3D Elo measures interactive 3D scene work; it is not a "
            "general intelligence score and not a CAD or printable-geometry "
            "score"
        ),
    }
