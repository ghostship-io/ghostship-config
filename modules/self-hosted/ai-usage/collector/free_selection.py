"""The free providers: the model each one selected, and the routes it holds free.

The Providers page lists every free provider. For each one it shows the
model the provider selected for the free tier, and the free routes the
provider holds apart from its paid allowance: the monthly allowance of
OpenCode Go is spent, and its free route still works.

Everything here is a projection of the routing snapshot. No provider is
read, and nothing is recomputed.

The contract::

    ghostship_ai_free_provider_selection_info{provider,model,display_name,basis} 1
    ghostship_ai_free_provider_selection_remaining_ratio{provider}
    ghostship_ai_free_provider_selection_paced_availability{provider}
    ghostship_ai_free_provider_selection_reset_timestamp_seconds{provider}
    ghostship_ai_provider_free_models{provider,state} count

A provider is a free provider when it holds a free route, or when every
window of its account was inferred: an account that only learned its
window is a free account, even when no route of it is in the inventory.
A route is free when its billing class says so, and the class alone
decides: the access kind of a route never makes it free.

The selection of a provider is the provider's first entry in
`tier_winners.free`, in the order of the tier. The basis of the selection
is the capacity of the winning route, read from the candidate of that
route: a reading the provider reported, an inference from the limit
failures of the route, or a statement the provider publishes. A route
that never saw a limit failure is learning its window, and the share it
has is still published. A provider with no free winner has no selection
and no basis.
"""

from __future__ import annotations

from typing import Any, Mapping

from metrics import ExactLabel, Sample
from util import iso_to_epoch

# The billing classes of a route that costs nothing. A dedicated free route
# is free, and a promotional route of a paid provider is free right now.
# The class is what the collector derived from the access of the route, and
# it is the only thing that decides: the access kind never does.
FREE_BILLING = ("free", "promotion")

# The bases a selection can carry. They are never mixed: a reader sees
# where the numbers of the selection came from.
BASIS_REPORTED = "reported"
BASIS_INFERRED = "inferred"
BASIS_PUBLISHED = "published"
# The route never saw a limit failure: the account is learning its
# window, and it holds no window of its own.
BASIS_LEARNING = "learning"
# Nothing was measured for the selection.
BASIS_NONE = "none"

# The state of an inference that saw no limit failure.
STATE_NO_FAILURE = "no_failure"

# The states a free route of a provider is in.
STATE_AVAILABLE = "available"
STATE_UNAVAILABLE = "unavailable"


def _number(value: Any) -> float | None:
    """A number, or None when the value is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _candidates(snapshot: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """The candidate rows of the snapshot."""
    rows = (snapshot or {}).get("candidates") or []
    return [row for row in rows if isinstance(row, Mapping)]


def _free_routes(
    candidates: list[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """The free routes of every provider, by provider.

    A route is free when its billing class is `free` or `promotion`. The
    access kind is not read: a route of a paid provider that is a
    subscription is not a free route, whatever its kind says.
    """
    found: dict[str, list[Mapping[str, Any]]] = {}
    for row in candidates:
        provider = str(row.get("provider") or "")
        if not provider:
            continue
        access = row.get("access")
        billing = str((access or {}).get("billing") or "") if isinstance(access, Mapping) else ""
        if billing not in FREE_BILLING:
            continue
        found.setdefault(provider, []).append(row)
    return found


def _accounts(snapshot: Mapping[str, Any] | None) -> dict[str, list[Mapping[str, Any]]]:
    """The account windows of the snapshot, by account."""
    quota = (snapshot or {}).get("quota") or {}
    accounts = quota.get("accounts") or {}
    if not isinstance(accounts, Mapping):
        return {}
    return {
        str(name): [record for record in records or [] if isinstance(record, Mapping)]
        for name, records in accounts.items()
    }


def _free_providers(
    accounts: Mapping[str, list[Mapping[str, Any]]],
    free_routes: Mapping[str, list[Mapping[str, Any]]],
) -> set[str]:
    """The providers that are free providers.

    A provider that holds a free route is one. A provider whose account
    holds only inferred windows is one too: such an account learned its
    window instead of reading it, and it belongs with the free providers
    even when no route of it is in the inventory.
    """
    providers = set(accounts) | set(free_routes)
    chosen: set[str] = set()
    for provider in providers:
        if free_routes.get(provider):
            chosen.add(provider)
            continue
        records = accounts.get(provider) or []
        if records and all(str(record.get("kind") or "") == "inferred" for record in records):
            chosen.add(provider)
    return chosen


def _winners(snapshot: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    """The first free winner of every provider, in the order of the tier."""
    winners = ((snapshot or {}).get("tier_winners") or {}).get("free") or []
    chosen: dict[str, Mapping[str, Any]] = {}
    for winner in winners:
        if not isinstance(winner, Mapping):
            continue
        provider = str(winner.get("provider") or "")
        if not provider or provider in chosen:
            continue
        chosen[provider] = winner
    return chosen


def _candidate_of(
    candidates: list[Mapping[str, Any]], provider: str, model: str
) -> Mapping[str, Any] | None:
    """The candidate of one route."""
    for row in candidates:
        if str(row.get("provider") or "") == provider and str(row.get("model") or "") == model:
            return row
    return None


def _basis(capacity: Mapping[str, Any]) -> str:
    """Where the capacity of the winning route comes from.

    A route that never saw a limit failure is learning its window, and the
    account card says so. A route with no capacity at all has no basis.
    """
    inference = capacity.get("inference")
    state = str(inference.get("state") or "") if isinstance(inference, Mapping) else ""
    if state == STATE_NO_FAILURE:
        return BASIS_LEARNING
    basis = str(capacity.get("capacity_basis") or "")
    if basis in (BASIS_REPORTED, BASIS_INFERRED, BASIS_PUBLISHED):
        return basis
    return BASIS_NONE


def samples(
    snapshot: Mapping[str, Any] | None,
    display_names: Mapping[tuple[str, str], str] | None = None,
) -> list[Sample]:
    """The free selection of every free provider, as Prometheus samples.

    The display name is the name the collector already publishes for the
    model, and the row falls back to the model id.
    """
    names = display_names or {}
    candidates = _candidates(snapshot)
    free_routes = _free_routes(candidates)
    accounts = _accounts(snapshot)
    winners = _winners(snapshot)
    published: list[Sample] = []
    for provider in sorted(_free_providers(accounts, free_routes)):
        winner = winners.get(provider)
        model = str(winner.get("model") or "") if winner else ""
        row = _candidate_of(candidates, provider, model) if winner else None
        capacity = {}
        if row is not None:
            found = row.get("capacity")
            if isinstance(found, Mapping):
                capacity = found
        basis = _basis(capacity) if winner else BASIS_NONE
        published.append(
            (
                "ghostship_ai_free_provider_selection_info",
                {
                    "provider": provider,
                    "model": model,
                    "display_name": ExactLabel(str(names.get((provider, model)) or model)),
                    "basis": basis,
                },
                1.0,
            )
        )
        remaining = _number(capacity.get("remaining_ratio"))
        if remaining is not None:
            published.append(
                (
                    "ghostship_ai_free_provider_selection_remaining_ratio",
                    {"provider": provider},
                    remaining,
                )
            )
        pace = _number(capacity.get("pace_delta"))
        if pace is not None:
            published.append(
                (
                    "ghostship_ai_free_provider_selection_paced_availability",
                    {"provider": provider},
                    pace,
                )
            )
        binding = capacity.get("capacity_binding")
        reset = (
            iso_to_epoch(str(binding.get("reset_at") or ""))
            if isinstance(binding, Mapping)
            else None
        )
        if reset is not None:
            published.append(
                (
                    "ghostship_ai_free_provider_selection_reset_timestamp_seconds",
                    {"provider": provider},
                    reset,
                )
            )
        routes = free_routes.get(provider) or []
        if not routes:
            # A provider that holds no free route has no free model to
            # count. Its account is free, and that is what the selection
            # says.
            continue
        available = sum(1 for route in routes if bool(route.get("available")))
        published.append(
            (
                "ghostship_ai_provider_free_models",
                {"provider": provider, "state": STATE_AVAILABLE},
                float(available),
            )
        )
        published.append(
            (
                "ghostship_ai_provider_free_models",
                {"provider": provider, "state": STATE_UNAVAILABLE},
                float(len(routes) - available),
            )
        )
    return published
