"""The owner's static worker table, read from the runtime policy.

While the routing switch is off, the table that governs every agent job is
`worker_routes.entries` of `config/agents/runtime-policy.json`. Each entry
names a task and a scope, and lists the routes to try in order. This module
turns that table into one row per model, so the Providers page can show the
selection that is in force.

The collector reads the policy, never writes it. The row's capacity is read
from the routing snapshot the collector already wrote, by provider and model,
so the table and the rest of the page come from the same measurements.

The contract::

    ghostship_ai_static_route_info{row,role,provider,model,display_name,used_for} 1
    ghostship_ai_static_route_remaining_ratio{row}
    ghostship_ai_static_route_paced_availability{row}
    ghostship_ai_static_route_reset_timestamp_seconds{row}
    ghostship_ai_static_route_policy_ok 1 | 0

A row is one model. The display order is the order of the page: the bulk
routes by their place in the bulk entry, then the large route, then the
deploy routes, then a route that only research uses. The role is the first
match of the table's own rules, and `used_for` names every entry that carries
the model, with the route's place in that entry. A missing or unreadable
policy publishes no row and `ghostship_ai_static_route_policy_ok 0`; the rest
of the collection is unaffected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import t3source
from metrics import ExactLabel, Sample, label_value
from util import iso_to_epoch

# The order the roles are read in. It is the order of the page and the order
# of the policy rules: a route of the bulk entry is a bulk route even when a
# later entry also names it.
_ROLE_BULK = 0
_ROLE_LARGE = 1
_ROLE_DEPLOYS = 2
_ROLE_RESEARCH = 3
_ROLE_OTHER = 4


def load(path: str | None) -> dict[str, Any] | None:
    """The runtime policy document, or None when it cannot be read.

    A document without a `worker_routes.entries` list is not a policy this
    module can read: it is reported as unreadable rather than as an empty
    table, because an empty table is a statement and a broken file is not.
    """
    if not path:
        return None
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    worker = document.get("worker_routes")
    if not isinstance(worker, dict):
        return None
    if not isinstance(worker.get("entries"), list):
        return None
    return document


def _priority(task_type: str, scope: str) -> int:
    """The rule that decides a model's role, first match wins."""
    if task_type == "implementation" and scope == "narrow":
        return _ROLE_BULK
    if task_type == "implementation" and scope == "large":
        return _ROLE_LARGE
    if task_type == "activation":
        return _ROLE_DEPLOYS
    if task_type == "research":
        return _ROLE_RESEARCH
    return _ROLE_OTHER


def _role(task_type: str, scope: str, position: int) -> str:
    """The role of the route that decides a model's row."""
    if task_type == "implementation" and scope == "narrow":
        return f"Bulk {position}"
    if task_type == "implementation" and scope == "large":
        return "Large"
    if task_type == "activation":
        return "Deploys"
    if task_type == "research":
        return "Research"
    return "Other"


def _task_label(task_type: str, scope: str) -> str:
    """How `used_for` names an entry."""
    if task_type == "activation":
        return "Deploys"
    if task_type == "research":
        return "Research"
    if task_type == "implementation":
        return f"{scope.capitalize()} implementation" if scope else "Implementation"
    return task_type.capitalize() if task_type else "Other"


def _ordinal(number: int) -> str:
    """1st, 2nd, 3rd, 4th ..."""
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _route(route: Mapping[str, Any]) -> tuple[str, str]:
    """The provider and model a route names.

    The OpenCode instance carries the account in its model id; the split is
    the collector's own, so the table and every other reading agree on a
    route's identity. Any other instance is the provider itself.
    """
    return t3source.split_model(
        str(route.get("instance_id") or ""), str(route.get("model") or "")
    )


def route_rows(document: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """One row per model of the static worker table, in display order."""
    if not isinstance(document, Mapping):
        return []
    worker = document.get("worker_routes")
    if not isinstance(worker, Mapping):
        return []
    entries = worker.get("entries")
    if not isinstance(entries, list):
        return []

    matches: dict[tuple[str, str], list[dict[str, Any]]] = {}
    first_seen: dict[tuple[str, str], int] = {}
    seen_order = 0
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        task_type = str(entry.get("task_type") or "")
        scope = str(entry.get("scope") or "")
        priority = _priority(task_type, scope)
        routes = entry.get("routes")
        if not isinstance(routes, list):
            continue
        named: set[tuple[str, str]] = set()
        for position, route in enumerate(routes, start=1):
            if not isinstance(route, Mapping):
                continue
            provider, model = _route(route)
            if not model:
                continue
            key = (provider, model)
            if key in named:
                # One entry names a model once; a repeat is the same place.
                continue
            named.add(key)
            matches.setdefault(key, []).append(
                {
                    "task_type": task_type,
                    "scope": scope,
                    "position": position,
                    "entry_index": entry_index,
                    "priority": priority,
                }
            )
            first_seen.setdefault(key, seen_order)
            seen_order += 1

    rows: list[dict[str, Any]] = []
    for (provider, model), found in matches.items():
        found.sort(key=lambda match: (match["priority"], match["entry_index"]))
        deciding = found[0]
        used_for = ", ".join(
            f"{_task_label(match['task_type'], match['scope'])}"
            f" ({_ordinal(match['position'])})"
            for match in found
        )
        rows.append(
            {
                "role": _role(
                    deciding["task_type"], deciding["scope"], deciding["position"]
                ),
                "provider": provider,
                "model": model,
                "used_for": used_for,
                "_rank": deciding["priority"],
                "_position": deciding["position"],
                "_first_seen": first_seen[(provider, model)],
            }
        )
    rows.sort(key=lambda row: (row["_rank"], row["_position"], row["_first_seen"]))
    for number, row in enumerate(rows, start=1):
        row["row"] = number
    return [
        {
            "row": row["row"],
            "role": row["role"],
            "provider": row["provider"],
            "model": row["model"],
            "used_for": row["used_for"],
        }
        for row in rows
    ]


def _candidates(snapshot: Mapping[str, Any] | None) -> dict[tuple[str, str], Mapping[str, Any]]:
    """The snapshot's candidate rows, by the route they name."""
    found: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in (snapshot or {}).get("candidates") or []:
        if not isinstance(row, Mapping):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not provider or not model:
            continue
        found.setdefault((provider, model), row)
    return found


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _display_name(
    names: Mapping[tuple[str, str], str], provider: str, model: str
) -> str:
    """The name the collector published for a model.

    The name is published with the model id the exposition format allows,
    and the id a provider gave is not always one of them: a slash and an
    at sign are not. The name is therefore looked up by the id of the
    route first, and by the published form of that id after it. The
    provider is part of the key, so the name of another provider's model
    is never used. A model without a published name falls back to its own
    id.
    """
    found = names.get((provider, model)) or names.get((provider, label_value(model)))
    return str(found or model)


def samples(
    policy_path: str | None,
    snapshot: Mapping[str, Any] | None,
    display_names: Mapping[tuple[str, str], str] | None = None,
) -> list[Sample]:
    """The static table as Prometheus samples.

    A row's capacity is read from the candidate of the same route: the share
    left, the Paced Availability, and the reset of the binding window. A
    route the snapshot does not carry keeps its info row and has no capacity
    series: an unknown capacity is never published as zero. The display name
    of a row is the name the collector already published for the model, and
    the row falls back to the model id. The name is found by the id of the
    route, and by the form of that id the exposition format allows, since a
    name is published under the latter.
    """
    document = load(policy_path)
    if document is None:
        return [("ghostship_ai_static_route_policy_ok", {}, 0.0)]

    names = display_names or {}
    candidates = _candidates(snapshot)
    published: list[Sample] = [("ghostship_ai_static_route_policy_ok", {}, 1.0)]
    for row in route_rows(document):
        number = str(row["row"])
        key = (row["provider"], row["model"])
        published.append(
            (
                "ghostship_ai_static_route_info",
                {
                    "row": number,
                    "role": ExactLabel(row["role"]),
                    "provider": row["provider"],
                    "model": row["model"],
                    "display_name": ExactLabel(
                        _display_name(names, row["provider"], row["model"])
                    ),
                    "used_for": ExactLabel(row["used_for"]),
                },
                1.0,
            )
        )
        candidate = candidates.get(key)
        if candidate is None:
            continue
        capacity = candidate.get("capacity")
        if not isinstance(capacity, Mapping):
            capacity = {}
        remaining = _number(capacity.get("remaining_ratio"))
        if remaining is not None:
            published.append(
                ("ghostship_ai_static_route_remaining_ratio", {"row": number}, remaining)
            )
        pace = _number(capacity.get("pace_delta"))
        if pace is not None:
            published.append(
                (
                    "ghostship_ai_static_route_paced_availability",
                    {"row": number},
                    pace,
                )
            )
        binding = capacity.get("capacity_binding")
        reset = (
            iso_to_epoch(binding.get("reset_at"))
            if isinstance(binding, Mapping)
            else None
        )
        if reset is not None:
            published.append(
                (
                    "ghostship_ai_static_route_reset_timestamp_seconds",
                    {"row": number},
                    reset,
                )
            )
    return published
