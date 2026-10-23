"""The availability of every account: can it serve right now, and why not.

An account whose limit was never seen used to reach the Providers page as a
bare "learning window" chip: the page could not say whether the account
could serve a request at all. The collector now publishes the answer, per
account: whether the account can serve right now, why it cannot when it
cannot, whether its limit is unpublished or still being learned, and when
that was observed.

Everything here is a projection of the routing snapshot. No provider is read,
and nothing is recomputed: the candidates of the snapshot say which routes
exist, what the collector already decided about them, and when it observed
them.

The contract::

    ghostship_ai_account_availability{account,state,basis,reason} 1
    ghostship_ai_account_availability_check_timestamp_seconds{account}

The routes of an account that count are its free or promotional routes when
it holds any, and all of its routes otherwise: a paid route never stands in
for a free one, and a free route never stands in for a paid one. The
account is available when one of the routes that count is available. The
reason of an account that cannot serve is the reason its routes carry most
often, and a route that is in cooldown names the moment it cools down. The
basis says where the limit of the account comes from: an account that never
saw a limit failure is learning its window, an account that publishes no
number has an unpublished limit, and every other account publishes one.

The reason is published exactly as it reads, and it is empty for an account
that can serve: an available account has no reason to give.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any, Mapping

from metrics import ExactLabel, Sample
from util import iso_to_epoch

# The billing classes of a route that costs nothing. A dedicated free route
# is free, and a promotional route of a paid provider costs nothing right
# now. The class is what the collector derived from the access of the route,
# and it is the only thing that decides.
FREE_BILLING = ("free", "promotion")

# The states an account is in. An account is available when one of the
# routes that count is available, and unavailable when none of them is.
STATE_AVAILABLE = "available"
STATE_UNAVAILABLE = "unavailable"

# The bases of the limit of an account. They are never mixed: a reader sees
# where the limit of the account comes from.
# The account never saw a limit failure: it is still learning its window.
BASIS_LEARNING = "learning"
# The account publishes no window with a number: its limit is unpublished.
BASIS_UNPUBLISHED = "unpublished"
# The account publishes a window of its own.
BASIS_PUBLISHED = "published"

# The state of an inference that saw no limit failure.
STATE_NO_FAILURE = "no_failure"

# The reason of an account whose routes say nothing. It is the last word of
# the collector, not a claim about the provider.
REASON_NO_ROUTE = "no route available"

# The reason of an account whose routes are all in cooldown. The moment is
# the earliest cooldown that has not run out yet.
REASON_COOLDOWN = "cooling down until {moment} UTC"


@dataclasses.dataclass(frozen=True)
class Availability:
    """The availability of one account.

    The state says whether the account can serve right now, the reason says
    why it cannot when it cannot, the basis says where the limit of the
    account comes from, and the check time says when the routes that count
    were observed.
    """

    account: str
    state: str
    basis: str
    reason: str
    check_time: float | None = None


def _candidates(snapshot: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """The candidate rows of the snapshot."""
    rows = (snapshot or {}).get("candidates") or []
    return [row for row in rows if isinstance(row, Mapping)]


def _by_account(
    candidates: list[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """The candidates of every account, by account."""
    found: dict[str, list[Mapping[str, Any]]] = {}
    for row in candidates:
        provider = str(row.get("provider") or "")
        if not provider:
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


def _billing(row: Mapping[str, Any]) -> str:
    """The billing class of a candidate."""
    access = row.get("access")
    if not isinstance(access, Mapping):
        return ""
    return str(access.get("billing") or "")


def _counted(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The routes of an account that count.

    An account that holds a free or a promotional route is counted by those
    routes alone: a paid route of the same account never stands in for a
    free one. An account that holds no free route is counted by all of its
    routes.
    """
    free = [row for row in rows if _billing(row) in FREE_BILLING]
    return free or rows


def _available(row: Mapping[str, Any]) -> bool:
    """Whether the candidate can be used right now.

    The snapshot publishes the judgement as a boolean, and only a boolean
    counts as an available route.
    """
    return row.get("available") is True


def _state(rows: list[Mapping[str, Any]]) -> str:
    """The state of an account: available, or unavailable."""
    for row in rows:
        if _available(row):
            return STATE_AVAILABLE
    return STATE_UNAVAILABLE


def _reason_of(row: Mapping[str, Any]) -> str:
    """The reason a candidate carries, or an empty string."""
    availability = row.get("availability")
    if not isinstance(availability, Mapping):
        return ""
    return str(availability.get("reason") or "")


def _cooldown(row: Mapping[str, Any]) -> float | None:
    """The moment the free pool cools a route down, when it published one."""
    pool = row.get("free_pool")
    if not isinstance(pool, Mapping):
        return None
    value = pool.get("cooldown_until")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        return iso_to_epoch(value)
    return None


def _cooldown_moment(rows: list[Mapping[str, Any]], now: float) -> str | None:
    """The moment the earliest cooldown of the routes that count ends.

    A cooldown that has run out is not a cooldown, and it never names the
    reason of an account.
    """
    moments = [
        moment
        for moment in (_cooldown(row) for row in rows)
        if moment is not None and moment > now
    ]
    if not moments:
        return None
    earliest = min(moments)
    return datetime.fromtimestamp(earliest, tz=timezone.utc).strftime("%H:%M")


def _reason(rows: list[Mapping[str, Any]], now: float) -> str:
    """Why an account cannot serve right now.

    The reason the routes carry most often is the reason of the account, and
    a route that says nothing does not count against a route that says
    something. When no route says anything, a route that is in cooldown names
    the moment it cools down, and an account that has no route at all says
    that it has none.
    """
    counts: dict[str, int] = {}
    order: list[str] = []
    for row in rows:
        reason = _reason_of(row)
        if not reason:
            continue
        if reason not in counts:
            counts[reason] = 0
            order.append(reason)
        counts[reason] += 1
    if counts:
        # The reason the routes carry most often. A tie keeps the reason
        # the routes carry first, so the answer never moves between two
        # collections of the same snapshot.
        return max(order, key=lambda reason: (counts[reason], -order.index(reason)))
    moment = _cooldown_moment(rows, now)
    if moment is not None:
        return REASON_COOLDOWN.format(moment=moment)
    return REASON_NO_ROUTE


def _has_number(record: Mapping[str, Any]) -> bool:
    """Whether a window of an account carries a number.

    A window that carries no number says nothing about the limit of the
    account, and an unknown window is never a zero.
    """
    for key in ("remaining_ratio", "used_ratio"):
        value = record.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return True
    return False


def _basis(records: list[Mapping[str, Any]]) -> str:
    """Where the limit of an account comes from.

    An account whose route never saw a limit failure is learning its
    window. An account that publishes no number has an unpublished limit,
    and every other account publishes one.
    """
    for record in records:
        inference = record.get("inference")
        if not isinstance(inference, Mapping):
            continue
        if str(inference.get("state") or "") == STATE_NO_FAILURE:
            return BASIS_LEARNING
    for record in records:
        if _has_number(record):
            return BASIS_PUBLISHED
    return BASIS_UNPUBLISHED


def _check_time(rows: list[Mapping[str, Any]]) -> float | None:
    """When the routes that count were observed, newest first.

    The check time of an account is the newest observation of the routes it
    is counted by: a paid route of the same account is not one of them.
    """
    moments: list[float] = []
    for row in rows:
        provenance = row.get("provenance")
        if not isinstance(provenance, Mapping):
            continue
        observed = str(provenance.get("observed_at") or "")
        if not observed:
            continue
        moment = iso_to_epoch(observed)
        if moment is not None:
            moments.append(moment)
    if not moments:
        return None
    return max(moments)


def accounts(
    snapshot: Mapping[str, Any] | None, now: float
) -> list[Availability]:
    """The availability of every account of the snapshot.

    An account is every key of the account windows of the snapshot and every
    provider of its candidates, so an account the snapshot knows only by its
    routes is published too.
    """
    records = _accounts(snapshot)
    candidates = _by_account(_candidates(snapshot))
    published: list[Availability] = []
    for account in sorted(set(records) | set(candidates)):
        rows = _counted(candidates.get(account) or [])
        state = _state(rows)
        published.append(
            Availability(
                account=account,
                state=state,
                basis=_basis(records.get(account) or []),
                # An account that can serve has no reason to give.
                reason=_reason(rows, now) if state == STATE_UNAVAILABLE else "",
                check_time=_check_time(rows),
            )
        )
    return published


def samples(
    snapshot: Mapping[str, Any] | None, now: float
) -> list[Sample]:
    """The availability of every account, as Prometheus samples.

    One series per account, and the labels of the series are the state, the
    basis of the limit and the reason. The check time of the account is
    published as its own series, and an account with no route to observe
    publishes none.
    """
    published: list[Sample] = []
    for record in accounts(snapshot, now):
        published.append(
            (
                "ghostship_ai_account_availability",
                {
                    "account": record.account,
                    "state": record.state,
                    "basis": record.basis,
                    # The reason is published as it reads, so the page can
                    # show the words the collector wrote.
                    "reason": ExactLabel(record.reason),
                },
                1.0,
            )
        )
        if record.check_time is not None:
            published.append(
                (
                    "ghostship_ai_account_availability_check_timestamp_seconds",
                    {"account": record.account},
                    record.check_time,
                )
            )
    return published
