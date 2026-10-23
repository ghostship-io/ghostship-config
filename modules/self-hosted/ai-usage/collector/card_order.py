"""The place every provider card takes on the Providers page.

The Providers page draws one card per provider account, and the cards come
in the order the owner approved. A Grafana variable keeps only the order of
the query that fills it, so the page cannot sort the cards itself: the
collector publishes the place of every account, and the page reads it.

Everything here is a projection of the routing snapshot. No provider is
read, and nothing is recomputed: the account windows of the snapshot say
which accounts exist and which of them publish a number, and the candidates
say which accounts hold a route.

The contract::

    ghostship_ai_account_card_order{account,scope} 1

The place is 1-based and holds no gap: the first card is 1, the last card is
the number of accounts, and every account holds exactly one series.

The order is the owner's approved list first, in the order the owner
approved it. The accounts that are not on the list follow: the ones that
publish at least one window with a number come first, by name, and the
accounts that are still learning their window come after them, by name. An
account of the approved list that the snapshot does not hold is skipped, and
the cards behind it move up: the places are the places of the cards that
exist, and they never leave a hole.
"""

from __future__ import annotations

from typing import Any, Mapping

from metrics import Sample

# The cards in the order the owner approved them. The names are the account
# names the collector publishes, and the list is the one the Providers page
# draws: Claude, Codex, Ollama, OpenCode Go, Antigravity, Grok and
# OpenRouter, and then the rest.
#
# The page and the README point at this list, and the collector publishes
# the place of every account beside it, so a change of the order is one
# change in one place.
APPROVED_CARD_ORDER = (
    "claude",
    "codex",
    "ollama",
    "opencode-go",
    "antigravity",
    "grok",
    "openrouter",
)


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


def _candidates(snapshot: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """The candidate rows of the snapshot."""
    rows = (snapshot or {}).get("candidates") or []
    return [row for row in rows if isinstance(row, Mapping)]


def _has_number(record: Mapping[str, Any]) -> bool:
    """Whether a window of an account carries a number.

    A window that carries no number says nothing about the limit of the
    account, and an unknown window is never a zero. A spent window carries
    the number zero, and a zero is a number.
    """
    for key in ("remaining_ratio", "used_ratio"):
        value = record.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return True
    return False


def accounts(snapshot: Mapping[str, Any] | None) -> set[str]:
    """The accounts the order covers.

    An account is every key of the account windows of the snapshot and every
    provider of its candidates, so an account the snapshot knows only by its
    routes is published too. It is the same set of accounts the availability
    of an account covers.
    """
    names = set(_accounts(snapshot))
    for row in _candidates(snapshot):
        provider = str(row.get("provider") or "")
        if provider:
            names.add(provider)
    return names


def order(snapshot: Mapping[str, Any] | None) -> list[str]:
    """The accounts, in the order their cards take.

    The approved list comes first, and an account of it that the snapshot
    does not hold is skipped. The accounts that are left follow: the ones
    that publish at least one window with a number, by name, and then the
    ones that publish none, by name.
    """
    known = accounts(snapshot)
    windows = _accounts(snapshot)
    approved = [name for name in APPROVED_CARD_ORDER if name in known]
    rest = known - set(approved)
    numbered = sorted(
        name
        for name in rest
        if any(_has_number(record) for record in windows.get(name) or [])
    )
    learning = sorted(rest - set(numbered))
    return approved + numbered + learning


def positions(snapshot: Mapping[str, Any] | None) -> list[tuple[str, int]]:
    """The place of every account, by account.

    The place is the place the card takes, counted from one, and the places
    hold no gap: an account that is not there leaves no hole behind it.
    """
    return [
        (name, place) for place, name in enumerate(order(snapshot), start=1)
    ]


def samples(snapshot: Mapping[str, Any] | None) -> list[Sample]:
    """The place of every account, as Prometheus samples.

    One series per account, and the value is the place its card takes.
    """
    native_accounts = {
        str(row.get("provider") or "")
        for row in _candidates(snapshot)
        if isinstance(row.get("native"), Mapping)
        and row["native"].get("mapped") is True
    }
    return [
        (
            "ghostship_ai_account_card_order",
            {"account": name, "scope": "t3" if name in native_accounts else "free"},
            float(place),
        )
        for name, place in positions(snapshot)
    ]
