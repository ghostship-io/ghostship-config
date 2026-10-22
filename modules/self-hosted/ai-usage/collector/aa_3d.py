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

import json
import math
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
    """One validated AA-3D record, or None when it is not usable evidence."""
    model = str(raw.get("model") or raw.get("name") or "").strip()
    elo = _finite(raw.get("elo"))
    source = str(raw.get("source") or "").strip()
    observed = _iso_epoch(raw.get("observed_at") or raw.get("observed_at_epoch"))
    if not model or elo is None or elo < 0.0 or not source:
        return None
    conditions = raw.get("conditions")
    if isinstance(conditions, Mapping):
        published_conditions = {
            str(key)[:40]: (
                value if isinstance(value, (str, int, float, bool)) else None
            )
            for key, value in list(conditions.items())[:20]
        }
    else:
        published_conditions = {"benchmark": str(raw.get("benchmark") or "aa-3d")[:60]}
    cost = _finite(raw.get("cost_per_task"))
    if cost is not None and (cost < 0.0 or not math.isfinite(cost)):
        cost = None
    interval = raw.get("elo_interval") or raw.get("interval") or raw.get("confidence_interval")
    low = high = None
    if isinstance(interval, Mapping):
        low = _finite(interval.get("low"))
        high = _finite(interval.get("high"))
    elif isinstance(interval, (list, tuple)) and len(interval) == 2:
        low = _finite(interval[0])
        high = _finite(interval[1])
    normalised = _finite(raw.get("normalized"))
    if normalised is not None and not 0.0 <= normalised <= 1.0:
        normalised = None
    return {
        "id": str(raw.get("id") or ""),
        "slug": str(raw.get("slug") or ""),
        "model": model[:120],
        "elo": round(elo, 1),
        "elo_interval": {
            "low": None if low is None else round(low, 1),
            "high": None if high is None else round(high, 1),
        },
        "cost_per_task": None if cost is None else round(cost, 6),
        "normalized": normalised,
        "normalization": str(raw.get("normalization") or "")[:80] or None,
        "source": source[:120],
        "observed_at": (
            datetime.fromtimestamp(observed, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if observed is not None
            else None
        ),
        "observed_at_epoch": observed,
        "released_at": str(raw.get("released_at") or "")[:40] or None,
        "task_count": int(raw["task_count"])
        if isinstance(raw.get("task_count"), (int, float))
        and not isinstance(raw.get("task_count"), bool)
        else None,
        "conditions": published_conditions,
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
    """The normalized 0..1 capability, using only the source's transform."""
    if not isinstance(elo, (int, float)) or isinstance(elo, bool):
        return None
    if not isinstance(normalization, Mapping):
        return None
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


def load_cache(path: str | None, now: float) -> dict[str, Any] | None:
    """The validated AA-3D snapshot, or None when it is absent or unusable."""
    if not path:
        return None
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, Mapping):
        return None
    records: list[dict[str, Any]] = []
    for raw in document.get("records") or ():
        if not isinstance(raw, Mapping):
            continue
        record = _record(raw)
        if record is not None:
            records.append(record)
    observed = _iso_epoch(
        document.get("fetched_at_epoch") or document.get("fetched_at")
    )
    age = None if observed is None else max(0.0, now - observed)
    status = "ok" if observed is not None and age is not None and age <= MAX_AGE_SECONDS else "stale"
    if not records:
        status = "missing"
    return {
        "status": status,
        "source": str(document.get("source") or "artificialanalysis")[:120],
        "benchmark": str(document.get("benchmark") or "aa-3d")[:60],
        "normalization": _normalization(document.get("normalization")),
        "conditions": str(
            document.get("conditions")
            or "interactive Three.js scenes; not a CAD or printable-geometry test"
        )[:160],
        "fetched_at": (
            datetime.fromtimestamp(observed, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if observed is not None
            else None
        ),
        "fetched_at_epoch": observed,
        "age_seconds": None if age is None else round(age, 1),
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
            "source" if record.get("normalized") is not None
            else ("applied" if normalised is not None else "unknown")
        ),
        "source": record.get("source"),
        "benchmark": str(cache.get("benchmark") or "aa-3d"),
        "conditions": record.get("conditions") or {},
        "observed_at": record.get("observed_at"),
        "released_at": record.get("released_at"),
        "task_count": record.get("task_count"),
        "aa_id": record.get("id"),
        "aa_slug": record.get("slug"),
        "aa_name": record.get("model"),
        "note": (
            "an AA-3D Elo measures interactive 3D scene work; it is not a "
            "general intelligence score and not a CAD or printable-geometry "
            "score"
        ),
    }
