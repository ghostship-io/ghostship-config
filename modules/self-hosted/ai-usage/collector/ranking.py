"""Rank every model we can use into tiers and report the ranks as gauges.

The ranking engine is the collector's opinion layer. It turns the raw
readings - the model inventory, the public model catalog, the subscription
windows, and the list of free models - into four ordered tiers:

* `frontier`: the best-value models, admitted automatically when a new model
  earns its place by quality, freshness, and size. Only the newest model of
  a lineage may hold the frontier, so a new release takes over from its
  predecessor without anyone editing a list.
* `bulk`: every other good, recent model, with the cheap and fast economy
  models weighted heavily, so the paid frontier accounts keep their capacity
  for frontier work.
* `free`: every model that can be used at no cost right now, including the
  promotional free models of paid providers.
* `3d`: the models worth using for 3D printing work, capped at a small
  number of the best ones. The 3D scores come from another component; this
  module never invents them.

The engine runs on every collection, so it never touches the network, keeps
no state beyond one small JSON file, and is deterministic: the same inputs
always produce the same ranks.

The tiers overlap only where the contract says so. A model of the frontier
is not listed again in the bulk tier, but it may be free and it may be
wanted for 3D work. A model that the inventory does not offer is reported
as unavailable and is never ranked.

The 3D scores are injected, never computed here. A caller passes a mapping
of `(provider, model)` to `{"score": 0..1, "usage_tokens": int,
"eligible": bool}`; a model without an `eligible` flag is not a 3D
candidate.

A caller may also narrow a tier: `exclude_providers` names the providers
that must not appear in a tier, and a quota window keyed by
`"provider/model"` replaces the account windows of that one model, which is
how a precise per-model quota wins over a shared family window.

Nothing here identifies a person. Only provider names, model ids, and
account aliases reach a metric label.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover - the collector always ships metrics.py
    from metrics import label_value
except ImportError:  # pragma: no cover - standalone use
    def label_value(value: object) -> str:
        return str(value)

try:  # pragma: no cover - the collector always ships catalog.py
    from catalog import PROVIDER_ALIASES
except ImportError:  # pragma: no cover - standalone use
    PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {}

try:  # pragma: no cover - the collector always ships aa_bind.py
    import aa_bind
except ImportError:  # pragma: no cover - standalone use
    aa_bind = None  # type: ignore[assignment]

try:  # pragma: no cover - the collector always ships value_policy.py
    import value_policy
except ImportError:  # pragma: no cover - standalone use
    value_policy = None  # type: ignore[assignment]

try:  # pragma: no cover - the collector always ships quota.py
    import quota as quota_module
except ImportError:  # pragma: no cover - standalone use
    quota_module = None  # type: ignore[assignment]


@dataclasses.dataclass
class ModelRecord:
    """One model we can use, with the provider that serves it."""

    provider: str
    model: str


@dataclasses.dataclass
class QuotaWindow:
    """One subscription or quota window of an account.

    `applies_to` names the model families the window belongs to, for the
    providers that report a window per family (Antigravity reports a Gemini
    window and a shared Claude and GPT window; Claude reports a separate
    weekly window for its Fable models). An empty tuple means the window
    applies to every model of the account.
    """

    kind: str
    used_ratio: float | None = None
    reset_epoch: float | None = None
    applies_to: tuple[str, ...] = ()
    quota_id: str = ""
    # How long the window runs. The pace of the usage is measured against it.
    duration_seconds: float | None = None
    # When the provider last reported this window. A reading that is older
    # than the freshness bound is stale, and a stale reading is not headroom.
    observed_at: float | None = None
    # Where the numbers of the window come from: a reading the provider
    # reported, a number its documentation publishes, or a published limit
    # counted against our own requests. The bases are never mixed.
    basis: str = ""
    # When the entitlement of the window ends, when the provider publishes
    # an end. A window without one has no end: it is unknown, never zero.
    ends_at: float | None = None
    # Whether the window constrains the route. A window a source publishes
    # without reading is visible and it does not gate: an unknown reading is
    # not evidence that an account is exhausted.
    gating: bool = True

    def applies(self, model: str) -> bool:
        """True when this window applies to the model."""
        if not self.applies_to:
            return True
        text = str(model or "").lower()
        return any(token.lower() in text for token in self.applies_to)


# The owner's frontier workhorses, and the only models that hold the frontier.
# The list is explicit policy, not a score: another model with a higher index
# does not take it over.
#
# This is the fallback. The runtime policy carries the owner's list, and the
# policy is what is read, so there is one list and not four.
FRONTIER_WORKHORSES = ("gpt-6.1-sol", "claude-opus-5-5")


@dataclasses.dataclass
class RankedModel:
    """One ranked model in one tier."""

    tier: str
    provider: str
    model: str
    rank: int
    score: float
    quality: float | None
    remaining: float | None
    expires_in_seconds: float | None
    available: bool
    # The evidence behind the rank, so a consumer can see what it is made of.
    reasons: tuple[str, ...] = ()
    windows: tuple[Any, ...] = ()
    settled: bool = True
    pending_reason: str = ""
    account: str = ""
    pace: float | None = None
    pace_binding: Any = None
    capacity_binding: Any = None
    applied_windows: tuple[Any, ...] = ()
    frontier_surplus: dict[str, Any] = dataclasses.field(default_factory=dict)
    quota_scope: dict[str, Any] = dataclasses.field(default_factory=dict)
    used_tokens: float = 0.0
    three_d_tokens: float = 0.0
    # The published value of the model under the owner's policy. It is the
    # score the tiers order by.
    value: float | None = None
    # The owner's frontier workhorses, as the runtime policy names them.
    workhorses: tuple[str, ...] = FRONTIER_WORKHORSES
    # The observed failure of the route, when there is one. The reason is a
    # code and a fixed label, never the provider's own text.
    observed_failure: dict[str, Any] = dataclasses.field(default_factory=dict)
    # Why the model is not usable right now, or an empty string when it is.
    # The reason is published with the availability, so a model that is not
    # offered stays visible with the reason it is not.
    availability_reason: str = ""
    # True when the provider publishes this route as unlimited. The route
    # then carries its own window and the paid allowance of the account
    # does not gate it.
    unlimited: bool = False


# The tiers, in the order the dashboard reads them.
TIERS = ("frontier", "bulk", "free", "3d")

# The reasons a model is not usable right now. They are fixed labels, never
# the provider's own text, and they are published with the availability of
# the model, so a reader knows why a route is not offered.
REASON_AVAILABLE = ""
REASON_ROUTE_FAILED = "the route failed and is not usable right now"
REASON_ROUTE_PARKED = "the route is parked by its own source"
REASON_CAPACITY_SPENT = "an allowance of the account is spent"
REASON_CAPACITY_UNKNOWN = "the headroom of the account is unknown"
REASON_NOT_OFFERED = "the route is not offered by the instance"

# Lineage priors. A model starts from the prior of its lineage, which is
# matched on the catalog family first and on the model id second.
LINEAGE_PRIORS: dict[str, float] = {
    "claude-opus": 100.0,
    "gpt-sol": 100.0,
    "gpt-astra": 96.0,
    "grok": 90.0,
    "gemini": 92.0,
    "minimax": 90.0,
    "claude-sonnet": 88.0,
    "claude-fable": 84.0,
    "deepseek-thinking": 86.0,
    "deepseek-pro": 86.0,
    "deepseek-flash": 80.0,
    "kimi-k3": 82.0,
    "kimi-k2": 76.0,
    "glm": 80.0,
    "qwen": 78.0,
    "gpt-luna": 78.0,
    "claude-haiku": 74.0,
    "longcat": 74.0,
    "mimo": 74.0,
    "muse": 70.0,
    "space-bunny": 60.0,
}
DEFAULT_PRIOR = 60.0

# A model id that carries one of these markers is a smaller sibling, never a
# frontier model.
SIZE_MARKERS = ("lite", "nano", "mini", "flash")

# A model id that carries one of these markers is an economy model: a small,
# fast, and cheap sibling of its lineage. These are the models the bulk tier
# prefers, so the paid frontier accounts keep their capacity for frontier
# work.
ECONOMY_MARKERS = (
    "flash",
    "mini",
    "nano",
    "lite",
    "air",
    "haiku",
    "luna",
    "small",
    "turbo",
)

# The per-million-token prices below which a model counts as cheap.
ECONOMY_MAX_INPUT_PRICE = 0.5
ECONOMY_MAX_OUTPUT_PRICE = 1.5

# The bulk tier weights an economy model up and every other model down.
ECONOMY_BULK_FACTOR = 2.0
PREMIUM_BULK_FACTOR = 0.85

# A model whose name or description says so is not yet a stable model.
PREVIEW_MARKERS = ("preview", "experimental", "beta")
PREVIEW_TOKEN = "rc"

# Days, in seconds.
DAY = 86400.0
FRONTIER_MAX_AGE_DAYS = 180.0
OLD_DAYS = 365.0

# The recency bonus of the quality score.
RECENT_DAYS = 30.0
RECENT_BONUS = 3.0
FRESH_DAYS = 90.0
FRESH_BONUS = 1.0

# A tier admits a model on measured evidence only: there is no quality
# threshold here, because a threshold would be a guess about a score the feed
# did not publish. The value and strength of a model are the measured
# Artificial Analysis record, and a model without one is unranked.

# The 3D tier stays small: only the best models are worth printing with.
THREE_D_MAX_MEMBERS = 20

# A model whose account has less than this share left cannot be used.
MIN_REMAINING = 0.05

# A quota reading older than this is stale. The collector reads the providers
# every five minutes, so half an hour is a generous bound; a stale reading
# never counts as headroom.
STALE_AFTER_SECONDS = 1800.0

# How close the reset of an entitlement window has to be for its surplus to
# be worth spending on volume work. The short session window is never one of
# them: it resets every few hours, and using it as an allowance would empty
# the review capacity days before the week or month does.
SURPLUS_WINDOW_KINDS = ("weekly", "monthly")
SURPLUS_EXPIRY_SECONDS = 24.0 * 3600.0

# A reading from the future is a clock problem, not a fresh measurement.
FUTURE_TOLERANCE_SECONDS = 60.0

# A model that was only just seen is not activated straight away. It needs a
# day of evaluation, or measured use, before it may hold a tier.
ADMISSION_GRACE_SECONDS = 24.0 * 3600.0

# A model that has been out for a day is not new any more.
RELEASE_SETTLE_DAYS = 1.0

# The urgency of a window decays over six hours to its reset.
URGENCY_HALF_LIFE_HOURS = 6.0

# The log scale of the 3D usage signal.
THREE_D_USAGE_LOG_RANGE = 6.0

# How much being behind the pace of a window counts. A model that is behind
# the line a window draws by now is consuming its allowance slowly, so it is
# preferred: that spreads the usage across every reset limit.
PACE_WEIGHT = 0.5


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _tokens(text: str) -> list[str]:
    return [part for part in re.split(r"[^a-z0-9]+", text.lower()) if part]


def _prior_matches(key: str, text: str) -> bool:
    """True when a lineage name describes a model id or a catalog family."""
    key_text = key.lower().strip()
    text_text = text.lower().strip()
    if not key_text or not text_text:
        return False
    if text_text == key_text:
        return True
    if text_text.startswith(key_text):
        # "grok" matches "grok-code" but not "grokish".
        tail = text_text[len(key_text):]
        if not tail[:1].isalpha():
            return True
    # "gpt-sol" describes "gpt-6.1-sol": the lineage tokens appear in order.
    key_tokens = _tokens(key_text)
    text_tokens = _tokens(text_text)
    if not key_tokens or len(key_tokens) > len(text_tokens):
        return False
    index = 0
    for token in text_tokens:
        if index < len(key_tokens) and token == key_tokens[index]:
            index += 1
    return index == len(key_tokens)


def _derived_lineage(model: str) -> str:
    """The lineage of a model id that no lineage name describes.

    The lineage is the leading words of the id, up to the first token that
    carries a version number: "gemini-3.8-flash" is the "gemini" lineage.
    """
    tokens = _tokens(model or "")
    if not tokens:
        return ""
    parts: list[str] = []
    for token in tokens:
        if any(character.isdigit() for character in token):
            break
        parts.append(token)
    if not parts:
        parts = [tokens[0].rstrip("0123456789")]
    return "-".join(parts)


def _lineage_key(family: str, model: str) -> str:
    """The lineage of a model: the catalog family first, the model id second."""
    for text in (family or "", model or ""):
        best = ""
        for key in LINEAGE_PRIORS:
            if len(key) > len(best) and _prior_matches(key, text):
                best = key
        if best:
            return best
    return _derived_lineage(model)


def _lineage_prior(family: str, model: str) -> float:
    """The prior of a model, taken from its family first and its id second."""
    return LINEAGE_PRIORS.get(_lineage_key(family, model), DEFAULT_PRIOR)


def _provider_keys(provider: str) -> tuple[str, ...]:
    """The catalog provider keys that may hold this collector provider."""
    keys = tuple(PROVIDER_ALIASES.get(provider, (provider,)))
    if provider not in keys:
        keys = keys + (provider,)
    return keys


def _catalog_entry(catalog: Any, provider: str, model: str) -> dict[str, Any]:
    """The raw catalog entry of one model, or an empty mapping."""
    document = getattr(catalog, "document", None)
    if not isinstance(document, Mapping):
        return {}
    for key in _provider_keys(provider):
        entry = document.get(key)
        if not isinstance(entry, Mapping):
            continue
        models = entry.get("models")
        if not isinstance(models, Mapping):
            continue
        found = models.get(model)
        if isinstance(found, Mapping):
            return dict(found)
    return {}


def _catalog_name(catalog: Any, provider: str, model: str) -> str:
    """The catalog name of a model, falling back to the model id."""
    getter = getattr(catalog, "model_name", None)
    if callable(getter):
        try:
            name = getter(provider, model)
        except Exception:  # pragma: no cover - defensive
            name = ""
        if isinstance(name, str) and name:
            return name
    entry = _catalog_entry(catalog, provider, model)
    name = entry.get("name")
    if isinstance(name, str) and name:
        return name
    return model


def _release_epoch(entry: Mapping[str, Any]) -> float | None:
    """The release date of a catalog entry as epoch seconds."""
    value = entry.get("release_date")
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            parsed_date = date.fromisoformat(text)
            return datetime(
                parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc
            ).timestamp()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _version_key(model: str) -> tuple[int, ...]:
    """The version numbers that a model id carries.

    "claude-opus-5-5" carries (5, 5) and "gpt-6.1-sol" carries (6, 1), so
    the ids can be ordered when the catalog knows no release date.
    """
    numbers: list[int] = []
    for token in _tokens(model or ""):
        for part in re.findall(r"\d+", token):
            numbers.append(int(part))
    return tuple(numbers)


def _newness(released: float | None, model: str, provider: str) -> tuple:
    """The key that orders the models of one lineage from old to new.

    A model with a release date is newer than a model without one. Among the
    models with a date the date decides, and among the models without one
    the version numbers of the model id decide.
    """
    dated = released is not None
    return (
        1 if dated else 0,
        released if dated else 0.0,
        _version_key(model),
        model,
        provider,
    )


def _context_window(entry: Mapping[str, Any]) -> float:
    limit = entry.get("limit")
    if not isinstance(limit, Mapping):
        return 0.0
    value = _as_float(limit.get("context"))
    return value if value is not None else 0.0


def _is_preview(*texts: str) -> bool:
    """True when a name or description marks an unstable model."""
    for text in texts:
        if not text:
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in PREVIEW_MARKERS):
            return True
        if any(token.startswith(PREVIEW_TOKEN) for token in _tokens(lowered)):
            return True
    return False


def quality_score(
    aa_cache: Mapping[str, Any] | None,
    provider: str,
    model: str,
    options: Any = None,
) -> float | None:
    """The measured Artificial Analysis intelligence index, or None.

    There is no fallback and no prior: a model the feed has not measured has
    no quality, and it is not ranked. The exact identity binding refuses a
    record of another model, release or reasoning variant.
    """
    record = _reference_record(aa_cache, provider, model)
    if record is None:
        return None
    indices = record.get("indices") or {}
    index = indices.get("intelligence_index")
    if isinstance(index, (int, float)) and not isinstance(index, bool):
        return float(index)
    return None


def _reference_record(
    aa_cache: Mapping[str, Any] | None,
    provider: str,
    model: str,
) -> Mapping[str, Any] | None:
    """The exact measured record of a model, or None.

    The model-selection reference is independent of the native setting: the
    best measured value among the exact records, not the record that
    matches a runtime option.
    """
    if aa_bind is None or not isinstance(aa_cache, Mapping):
        return None
    if aa_cache.get("status") != "ok":
        return None
    binding = aa_bind.resolve(
        aa_cache.get("records") or (), provider, model, mode="reference"
    )
    if binding.get("state") != "measured":
        return None
    if binding.get("reference") is None:
        return None
    record = binding.get("record")
    return record if isinstance(record, Mapping) else None


def value_score(
    aa_cache: Mapping[str, Any] | None,
    provider: str,
    model: str,
    options: Any = None,
) -> float | None:
    """The published value of a model, or None.

    This is the value the owner's policy defines: the measured
    intelligence and the measured cost per task, with the weights and the
    transform of the policy. It is the number the tiers order by and the
    number the workload recommendation picks, so the published score and
    the decision cannot disagree.
    """
    record = _reference_record(aa_cache, provider, model)
    if record is None:
        return None
    indices = record.get("indices") or {}
    index = indices.get("intelligence_index")
    if not isinstance(index, (int, float)) or isinstance(index, bool):
        return None
    cost = record.get("cost_per_task")
    efficiency, _evidence = value_policy.cost_transform(
        cost, (), value_policy.DEFAULT_COST_TRANSFORM
    )
    if efficiency is None:
        return None
    value, _missing = value_policy.combine(
        {"intelligence": float(index) / 100.0, "cost_per_task": efficiency},
        value_policy.VALUE_WEIGHTS,
    )
    return None if value is None else round(value, 6)


# The accounts a provider name maps to. The provider name wins over the model
# id, so a model served through an account keeps that account.
KNOWN_ACCOUNTS = (
    "claude",
    "codex",
    "grok",
    "antigravity",
    "opencode-go",
    "ollama",
    "openrouter",
)

# The account of a provider. The provider name is authoritative: the quota
# windows are reported per account, and the account that serves a model is
# the provider the model is offered by.
#
# The catalog keys of the paid accounts are mapped back onto their account.
# That is the inverse of the alias the catalog already declares, not a guess
# about a model: the collector names these providers "claude" and "codex",
# and the catalog calls them "anthropic" and "openai".
#
# The free pool's own provider ids keep their identity. "gpt-oss-120b" on the
# pool's "ovh" provider is not a Codex model, "gemini-3.8-flash" on the pool's
# "google" provider is not an Antigravity model, and the OpenCode route is
# not the Grok account. "google" is deliberately not mapped: it is a free
# pool provider, and the Antigravity account is reached by its own name.
ACCOUNT_OF_PROVIDER = {
    "anthropic": "claude",
    "openai": "codex",
    "xai": "grok",
}

# The native T3 Code provider instances that may name a paid account by the
# vendor prefix of their model id, and only when the account of that instance
# is genuinely that vendor's subscription.
#
# The list is empty on purpose: every provider the collector knows is its own
# account, so a model id prefix is never an account. The mechanism stays here
# so a future native instance can be added without changing the rule.
NATIVE_INSTANCE_ACCOUNT_PREFIXES: dict[str, dict[str, str]] = {}


def account_for(provider: str, model: str) -> str:
    """The account that serves a model.

    The provider is the account. A free pool provider and the OpenCode route
    keep their own account, so an exhausted Codex allowance never removes a
    pool model or an OpenCode route from a tier.
    """
    name = str(provider or "")
    if name in KNOWN_ACCOUNTS:
        return name
    mapped = ACCOUNT_OF_PROVIDER.get(name)
    if mapped is not None:
        return mapped
    prefixes = NATIVE_INSTANCE_ACCOUNT_PREFIXES.get(name) or {}
    model_id = str(model or "")
    for prefix, account in prefixes.items():
        if model_id.startswith(prefix):
            return account
    return name


def _window_used_strict(window: Any) -> float | None:
    """The usage share of a window, or None when it is missing or malformed."""
    ratio = getattr(window, "used_ratio", None)
    if ratio is None and isinstance(window, Mapping):
        ratio = window.get("used_ratio")
    if ratio is None or isinstance(ratio, bool):
        return None
    if not isinstance(ratio, (int, float)):
        return None
    value = float(ratio)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        return None
    return value


def _window_used(window: Any) -> float:
    ratio = getattr(window, "used_ratio", None)
    if ratio is None and isinstance(window, Mapping):
        ratio = window.get("used_ratio")
    value = _as_float(ratio)
    return value if value is not None else 0.0


def _window_reset(window: Any) -> float | None:
    reset = getattr(window, "reset_epoch", None)
    if reset is None and isinstance(window, Mapping):
        reset = window.get("reset_epoch")
    return _as_float(reset)


def _capacity_detail(
    windows: list[Any], now: float
) -> dict[str, Any]:
    """The capacity of an account and the pace of its usage.

    The pace compares the measured usage with the line a window of this
    length would have drawn by now: a model that is behind that line is
    consuming its allowance slowly, so using it now spreads the usage
    across every reset limit instead of piling it on one account.
    """
    empty = {
        "remaining": None,
        "expiresIn": None,
        "urgency": 0.0,
        "pace": None,
        "expected": None,
        "actual": None,
        "binding": None,
        "paceBinding": None,
        "paceValue": None,
        "paceExpected": None,
        "paceActual": None,
    }
    # A window a source publishes without reading stays visible, but it does
    # not constrain the route: an unknown reading is not evidence that an
    # account is exhausted, and a provider is never hidden by it.
    gating = [
        window
        for window in windows
        if getattr(window, "gating", True) is not False
    ]
    if not gating:
        return dict(empty)
    windows = gating
    states: list[tuple[Any, str, float | None]] = []
    for window in windows:
        state, remaining = _window_state(window, now)
        states.append((window, state, remaining))
    spent = [item for item in states if item[1] == "known" and item[2] == 0.0]
    if spent:
        # A window that is known to be spent gates the model, whatever else
        # is unknown about the other windows.
        binding = min(spent, key=lambda item: _reset_sort_key(item[0]))
        reset = _window_reset(binding[0])
        return {
            **empty,
            "remaining": 0.0,
            "expiresIn": None if reset is None else reset - now,
            "binding": binding[0],
        }
    if any(state == "unknown" for _window, state, _remaining in states):
        return dict(empty)
    binding = min(
        states,
        key=lambda item: (
            item[2] if item[2] is not None else 0.0,
            _reset_sort_key(item[0]),
        ),
    )
    remaining = binding[2] if binding[2] is not None else 0.0
    reset = _window_reset(binding[0])
    expires_in = None if reset is None else reset - now
    urgency = 0.5 if reset is None else 1.0 / (
        1.0 + max(0.0, (reset - now) / 3600.0) / URGENCY_HALF_LIFE_HOURS
    )
    expected, actual = _pace(binding[0], now, remaining)
    paces: list[tuple[Any, float, float, float]] = []
    for window, state, remaining_value in states:
        if state != "known" or remaining_value is None:
            continue
        window_expected, window_actual = _pace(window, now, remaining_value)
        if window_expected is None or window_actual is None:
            continue
        paces.append(
            (window, window_expected, window_actual, window_expected - window_actual)
        )
    pace_binding = min(paces, key=lambda item: item[3]) if paces else None
    return {
        "remaining": remaining,
        "expiresIn": expires_in,
        "urgency": urgency,
        "pace": None if expected is None else max(-1.0, min(1.0, expected - actual)),
        "expected": expected,
        "actual": actual,
        "binding": binding[0],
        # The pace binding is the most constraining window, which is not
        # necessarily the capacity binding: a window can be lightly used and
        # still run out first because its own line is far ahead.
        "paceBinding": None if pace_binding is None else pace_binding[0],
        "paceValue": None if pace_binding is None else max(-1.0, min(1.0, pace_binding[3])),
        "paceExpected": None if pace_binding is None else pace_binding[1],
        "paceActual": None if pace_binding is None else pace_binding[2],
    }


def _pace(window: Any, now: float, remaining: float) -> tuple[float | None, float | None]:
    """The expected usage of a window by now and the measured usage.

    The expected usage is the line a window of this length draws between its
    start and its reset. A negative difference means the account is behind
    that line.
    """
    duration = getattr(window, "duration_seconds", None)
    if duration is None and isinstance(window, Mapping):
        duration = window.get("duration_seconds")
    reset = _window_reset(window)
    if not duration or duration <= 0 or reset is None:
        return None, None
    start = reset - float(duration)
    elapsed = now - start
    expected = min(1.0, max(0.0, elapsed / float(duration)))
    actual = max(0.0, min(1.0, 1.0 - remaining))
    return expected, actual


def _window_state(window: Any, now: float) -> tuple[str, float | None]:
    """Classify one window as known, spent, or unknown.

    A window is only known when the provider reported a usage share that is a
    number inside its range, and when its reset is not already behind us: a
    reset in the past is a stale reading, not a refill. A window that is
    missing, malformed, or stale is unknown, which is neither healthy
    headroom nor a spent allowance.
    """
    used = _window_used_strict(window)
    if used is None:
        return "unknown", None
    reset = _window_reset(window)
    if reset is not None and reset <= now:
        # The window expired before this reading. The provider has to report
        # the new window before the headroom can be claimed again.
        return "unknown", None
    if not _reading_is_fresh(window, now):
        # The reading is stale, or its time is not credible. It is not
        # headroom, and it is not fresh either.
        return "unknown", None
    return "known", max(0.0, 1.0 - used)


def _reading_is_fresh(window: Any, now: float) -> bool:
    """True when a window was read recently enough to be believed."""
    observed = getattr(window, "observed_at", None)
    if observed is None and isinstance(window, Mapping):
        observed = window.get("observed_at")
    if observed is None:
        return False
    if not isinstance(observed, (int, float)) or isinstance(observed, bool):
        return False
    value = float(observed)
    if not math.isfinite(value):
        return False
    if value > now + FUTURE_TOLERANCE_SECONDS:
        return False
    return (now - value) <= STALE_AFTER_SECONDS


def _capacity(windows: list[Any], now: float) -> tuple[float | None, float | None, float]:
    """Return the remaining share, the seconds to the reset, and the urgency.

    Every window that applies to a model gates it. The most constrained
    window decides the capacity: a spent weekly window means the account has
    no headroom, even when a shorter session window still shows room. The
    urgency decays towards the reset of that window, so capacity that
    expires soon outranks capacity that stays available for days.
    """
    detail = _capacity_detail(windows, now)
    return detail["remaining"], detail["expiresIn"], detail["urgency"]


def _reset_sort_key(window: Any) -> float:
    """Sort key that puts the window that resets soonest first."""
    reset = _window_reset(window)
    return reset if reset is not None else float("inf")


def _record_pair(record: Any) -> tuple[str, str] | None:
    """Normalise a model reference into a (provider, model) pair."""
    provider = getattr(record, "provider", None)
    model = getattr(record, "model", None)
    if isinstance(provider, str) and isinstance(model, str) and provider and model:
        return provider, model
    if isinstance(record, Mapping):
        provider = record.get("provider")
        model = record.get("model")
        if isinstance(provider, str) and isinstance(model, str) and provider and model:
            return provider, model
    if isinstance(record, (tuple, list)) and len(record) == 2:
        provider, model = record
        if isinstance(provider, str) and isinstance(model, str) and provider and model:
            return provider, model
    return None


def _state_key(provider: str, model: str) -> str:
    return f"{provider}/{model}"


def _load_state(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read the ranking state file, tolerating a missing or broken file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _update_state(state: dict[str, Any], present: set[str], now: float) -> dict[str, Any]:
    """Record the evaluation of every model we know about."""
    updated: dict[str, Any] = {}
    for key, entry in state.items():
        if not isinstance(entry, Mapping):
            entry = {}
        record = dict(entry)
        record["stale"] = key not in present
        updated[key] = record
    for key in sorted(present):
        record = dict(updated.get(key) or {})
        first_seen = _as_float(record.get("first_seen"))
        if first_seen is None:
            record["first_seen"] = now
        evaluations = record.get("evaluations")
        if not isinstance(evaluations, int) or isinstance(evaluations, bool):
            evaluations = 0
        record["evaluations"] = evaluations + 1
        record["last_evaluated"] = now
        record["stale"] = False
        updated[key] = record
    return updated


def _save_state(path: str | os.PathLike[str], state: dict[str, Any]) -> None:
    """Write the ranking state file atomically."""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, target)
    except OSError:
        pass


def _three_d_values(entry: Any) -> tuple[float, float, bool]:
    """The measured 3D usage tokens and the explicit eligibility of a model.

    Eligibility is the caller's verified evidence: the catalog proves the
    model can read an image and the workload admission is explicit. There is
    no prior and no score here; the tier orders by the measured record.
    """
    if not isinstance(entry, Mapping):
        return 0.0, 0.0, False
    tokens = _as_float(entry.get("usage_tokens"))
    if tokens is None:
        tokens = _as_float(entry.get("tokens"))
    eligible = bool(entry.get("eligible", False))
    # The score is the measured AA-3D Elo. No Elo means no 3D rank; the
    # general intelligence index is never a stand-in.
    score = _as_float(entry.get("elo"))
    return (score or 0.0), (tokens or 0.0), eligible


def _three_d_usage_score(tokens: float) -> float:
    """The log scaled 3D usage signal, from 0 to 100."""
    if tokens <= 0:
        return 0.0
    return min(100.0, math.log10(tokens + 1.0) / THREE_D_USAGE_LOG_RANGE * 100.0)


def _has_marker(model: str, markers: Iterable[str]) -> bool:
    """True when a model id names one of the markers.

    The marker is matched on a whole id token, so "gemini" and "minimax"
    are not read as the "mini" marker. A token that continues with a digit,
    such as "flash2", still counts.
    """
    for token in _tokens(model or ""):
        for marker in markers:
            if token == marker:
                return True
            if token.startswith(marker) and token[len(marker):len(marker) + 1].isdigit():
                return True
    return False


def _has_size_marker(model: str) -> bool:
    """True when a model id names a smaller sibling of its family."""
    return _has_marker(model, SIZE_MARKERS)


def _is_cheap(entry: Mapping[str, Any]) -> bool:
    """True when the catalog prices a model below the cheap thresholds."""
    cost = entry.get("cost")
    if not isinstance(cost, Mapping):
        return False
    input_price = _as_float(cost.get("input"))
    output_price = _as_float(cost.get("output"))
    if input_price is None or output_price is None:
        return False
    return (
        input_price <= ECONOMY_MAX_INPUT_PRICE
        and output_price <= ECONOMY_MAX_OUTPUT_PRICE
    )


def _is_economy(entry: Mapping[str, Any], model: str) -> bool:
    """True when a model is an economy model.

    An economy model is a small sibling of its lineage - one whose id says so
    - or a model the catalog prices cheaply.
    """
    return _has_marker(model, ECONOMY_MARKERS) or _is_cheap(entry)


def _excluded_providers(
    exclude_providers: Mapping[str, Iterable[str]] | None,
) -> dict[str, set[str]]:
    """The providers that must not appear in a tier."""
    excluded: dict[str, set[str]] = {}
    for tier, providers in (exclude_providers or {}).items():
        names = {str(provider).strip().lower() for provider in providers or ()}
        names.discard("")
        if names:
            excluded[str(tier)] = names
    return excluded


def _quota_windows(
    quota_windows: Mapping[str, Iterable[Any]] | None,
) -> tuple[dict[str, list[Any]], dict[tuple[str, str], list[Any]]]:
    """Split the quota windows into the account windows and the model windows.

    A key of the form "provider/model" holds the windows of that one model
    and replaces the account windows for it.
    """
    by_account: dict[str, list[Any]] = {}
    by_model: dict[tuple[str, str], list[Any]] = {}
    for key, windows in (quota_windows or {}).items():
        text = str(key)
        if "/" in text:
            provider, _, model = text.partition("/")
            by_model[(provider, model)] = list(windows or [])
        else:
            by_account[text] = list(windows or [])
    return by_account, by_model


@dataclasses.dataclass
class _Candidate:
    """One model we know about, with everything the tiers need."""

    provider: str
    model: str
    quality: float | None
    value: float | None
    available: bool
    fresh: bool
    small: bool
    economy: bool
    lineage: str
    newness: tuple
    capacity_bonus: float
    remaining: float | None
    expires_in: float | None
    free: bool
    three_d_score: float
    three_d_tokens: float
    three_d_eligible: bool
    settled: bool
    pending_reason: str
    used_tokens: float
    windows: list[Any]
    pace: float | None
    expected: float | None
    actual: float | None
    account: str
    quota_scope: dict[str, Any]
    pace_binding: Any
    capacity_binding: Any
    frontier_surplus: dict[str, Any]
    applied_windows: list[Any]
    # True when the provider publishes this route as unlimited. The route
    # then carries its own window and the paid allowance of the account
    # does not gate it.
    unlimited: bool = False
    # Why the model is not usable right now, or an empty string when it is.
    availability_reason: str = ""
    # The owner's frontier workhorses, as the runtime policy names them.
    workhorses: tuple[str, ...] = FRONTIER_WORKHORSES

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.model)

    @property
    def frontier_worthy(self) -> bool:
        """True when a model may hold the frontier of its lineage.

        A model holds the frontier when it is good enough, when it is
        available, when it was released recently, and when it is one of the
        owner's workhorses.
        """
        return (
            self.available
            # A model with no measured record is never a frontier candidate,
            # and neither is a model outside the owner's explicit workhorse
            # list.
            and self.quality is not None
            and str(self.model) in self.workhorses
            and self.fresh
            and not self.small
            # A promotional free model is not a frontier account: it belongs
            # to the free and bulk tiers.
            and not self.free
        )


def _frontier_winners(candidates: list[_Candidate]) -> set[tuple[str, str]]:
    """The models that may hold the frontier, one per lineage.

    A lineage holds the frontier with its newest model, so a new release
    takes over from its predecessor on its own. The lineage of a model is
    the catalog family when the catalog knows it, and a lineage derived
    from the model id otherwise.
    """
    best: dict[str, _Candidate] = {}
    for candidate in candidates:
        if not candidate.frontier_worthy:
            continue
        current = best.get(candidate.lineage)
        if current is None or candidate.newness > current.newness:
            best[candidate.lineage] = candidate
    return {candidate.key for candidate in best.values()}


def _frontier_surplus(
    windows: list[Any], now: float
) -> dict[str, Any]:
    """The surplus of a frontier model that is about to expire.

    A weekly or monthly allowance that resets within a day will be lost if
    it is not used, so it may carry volume work. The short session window
    never counts: it would let the review capacity be spent days early.
    The session window also holds the reserve: when it is ahead of the line
    the review capacity is under pressure, and nothing is spared.
    """
    expiring: list[tuple[Any, float | None]] = []
    session: tuple[Any, float | None] | None = None
    for window in windows:
        state, remaining = _window_state(window, now)
        kind = getattr(window, "kind", None)
        if kind is None and isinstance(window, Mapping):
            kind = window.get("kind")
        kind = str(kind or "")
        reset = _window_reset(window)
        if state != "known" or remaining is None:
            continue
        if kind in SURPLUS_WINDOW_KINDS and reset is not None:
            expires_in = reset - now
            if 0 <= expires_in <= SURPLUS_EXPIRY_SECONDS:
                expiring.append((window, remaining))
        elif kind == "session":
            session = (window, remaining)
    if not expiring:
        return {
            "available": False,
            "reason": "no weekly or monthly allowance resets within a day",
            "expires_in_seconds": None,
            "surplus_ratio": 0.0,
            "reserve_ratio": None,
            "pace_delta": None,
            "entitlement_kind": None,
            "entitlement_duration_seconds": None,
            "entitlement_reset_at": None,
            "entitlement_quota_id": None,
        }
    window, remaining = max(expiring, key=lambda item: item[1])
    reset = _window_reset(window)
    expires_in = None if reset is None else int(round(reset - now))
    reserve = session[1] if session is not None else None
    duration = getattr(window, "duration_seconds", None)
    if duration is None and isinstance(window, Mapping):
        duration = window.get("duration_seconds")
    quota_id = getattr(window, "quota_id", None)
    if quota_id is None and isinstance(window, Mapping):
        quota_id = window.get("quota_id")
    entitlement = {
        "entitlement_kind": str(getattr(window, "kind", "") or ""),
        "entitlement_duration_seconds": (
            int(duration) if isinstance(duration, (int, float)) and duration else None
        ),
        "entitlement_reset_at": (
            datetime.fromtimestamp(reset, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if reset is not None
            else None
        ),
        "entitlement_quota_id": str(quota_id or ""),
    }
    _expected, _actual = _pace(window, now, remaining)
    pace = None
    if session is not None and session[1] is not None:
        expected, actual = _pace(session[0], now, session[1])
        if expected is not None and actual is not None:
            pace = expected - actual
    if reserve is not None and pace is not None and pace < 0:
        # The session window is ahead of the line: the review capacity is
        # under pressure, so nothing is spared.
        return {
            "available": False,
            "reason": "the session window is ahead of the line; the review capacity is under pressure",
            "expires_in_seconds": expires_in,
            "surplus_ratio": 0.0,
            "reserve_ratio": round(reserve, 4),
            "pace_delta": round(pace, 4),
            **entitlement,
        }
    if remaining <= 0:
        return {
            "available": False,
            "reason": "the expiring allowance is already spent",
            "expires_in_seconds": expires_in,
            "surplus_ratio": 0.0,
            "reserve_ratio": None if reserve is None else round(reserve, 4),
            "pace_delta": None if pace is None else round(pace, 4),
            **entitlement,
        }
    return {
        "available": True,
        "reason": "an allowance resets within a day and the review capacity is not under pressure",
        "expires_in_seconds": expires_in,
        "surplus_ratio": round(remaining, 4),
        "reserve_ratio": None if reserve is None else round(reserve, 4),
        "pace_delta": None if pace is None else round(pace, 4),
        **entitlement,
    }


def _reasons(candidate: "_Candidate", tier: str) -> list[str]:
    """The short reasons behind a rank, so it can be explained."""
    reasons: list[str] = []
    if candidate.quality is None:
        reasons.append("no verified Artificial Analysis record: unranked")
    else:
        reasons.append(f"quality {candidate.quality:.0f} (the verified index)")
    if candidate.unlimited:
        # The provider publishes this route as unlimited for a limited time,
        # so it is not gated by the paid allowance of the account and it is
        # a promotion, not a permanent entitlement.
        reasons.append(
            "unlimited (limited-time promotion): the provider publishes this "
            "route as unlimited for a limited time"
        )
    if candidate.remaining is None:
        reasons.append("capacity unknown: the provider reported no usable window")
    else:
        reasons.append(f"capacity {candidate.remaining * 100:.0f}% left")
        if candidate.expires_in is not None:
            reasons.append(f"that capacity expires in {int(candidate.expires_in)}s")
    if candidate.pace is not None:
        reasons.append(
            f"{'behind' if candidate.pace > 0 else 'ahead of'} the usage line "
            f"by {abs(candidate.pace) * 100:.0f}%"
        )
    elif candidate.remaining is not None:
        reasons.append("the pace against the reset window is unknown")
    if candidate.used_tokens > 0:
        reasons.append(f"{int(candidate.used_tokens)} tokens used in the last seven days")
    if candidate.economy:
        reasons.append("an economy model: cheap and fast")
    if candidate.free:
        reasons.append("free to use")
    if not candidate.settled:
        reasons.append(candidate.pending_reason)
    return reasons


def _is_allowance_window(window: Any) -> bool:
    """True when a window is a paid allowance of the account."""
    kind = getattr(window, "kind", None)
    if kind is None and isinstance(window, Mapping):
        kind = window.get("kind")
    return str(kind or "") in ("session", "weekly", "monthly", "subscription")


def _is_unlimited_window(window: Any) -> bool:
    """True when a window states that the route is published as unlimited.

    The window is the provider's own published statement about one route,
    and it is scoped to that route. The paid allowance of the account does
    not gate a route the provider publishes as unlimited: the two are
    different entitlements.
    """
    quota_id = getattr(window, "quota_id", None)
    if quota_id is None and isinstance(window, Mapping):
        quota_id = window.get("quota_id")
    return str(quota_id or "") == "free-unlimited"


def _window_applies(window: Any, model: str) -> bool:
    """True when a window applies to the model."""
    applies = getattr(window, "applies_to", None)
    if applies is None and isinstance(window, Mapping):
        applies = window.get("applies_to")
    if not applies:
        return True
    text = str(model or "").lower()
    return any(str(token).lower() in text for token in applies)


def _admission(
    provider: str,
    model: str,
    state: Mapping[str, Any],
    used_tokens: float,
    released: float | None,
    now: float,
) -> tuple[bool, str]:
    """Decide whether a model may hold a tier yet.

    A model is activated once it has been out for a day, or once it has been
    used, or once the collector has seen it for a day. A model that was only
    just seen waits: a name in a catalog is not a measurement.
    """
    if released is not None and (now - released) / DAY >= RELEASE_SETTLE_DAYS:
        return True, ""
    if used_tokens > 0:
        return True, ""
    record = state.get(_state_key(provider, model))
    first_seen = None
    if isinstance(record, Mapping):
        first_seen = _as_float(record.get("first_seen"))
    if first_seen is not None and (now - first_seen) >= ADMISSION_GRACE_SECONDS:
        return True, ""
    if first_seen is None:
        return False, "first seen in this collection; the evaluation window has not elapsed"
    return (
        False,
        "first seen "
        + str(int(first_seen))
        + "; the evaluation window ends "
        + str(int(first_seen + ADMISSION_GRACE_SECONDS)),
    )


def _observed_failures(
    failures: Iterable[Mapping[str, Any]] | None,
) -> dict[str, list[Mapping[str, Any]]]:
    """The observed failures, grouped by the scope they apply to.

    The three scopes are kept apart: an account failure reaches every
    model of that account, a route failure every model of that provider
    instance, and a model failure only that model.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for failure in failures or ():
        if not isinstance(failure, Mapping):
            continue
        scope = str(failure.get("scope") or "")
        target = str(failure.get("target") or "")
        if not scope or not target:
            continue
        grouped.setdefault(f"{scope}:{target}", []).append(dict(failure))
    return grouped


def _failure_for(
    failures: Mapping[str, list[Mapping[str, Any]]],
    account: str,
    provider_instance: str,
    model: str,
) -> Mapping[str, Any] | None:
    """The failure that reaches a model, if there is one."""
    for key in (
        f"account:{account}",
        f"route:{provider_instance}",
        f"model:{model}",
    ):
        found = failures.get(key)
        if found:
            return max(found, key=lambda entry: float(entry.get("observed_at") or 0.0))
    return None


def rank_models(
    *,
    models: Iterable[Any],
    catalog: Any,
    quota_windows: Mapping[str, Iterable[Any]] | None,
    free_models: Iterable[Any],
    promo_models: Iterable[Any] | None = None,
    external_availability: Mapping[tuple[str, str], bool] | None = None,
    usage_tokens: Mapping[tuple[str, str], float] | None = None,
    three_d_scores: Mapping[tuple[str, str], Any] | None = None,
    aa_cache: Mapping[str, Any] | None = None,
    native_models: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    exclude_providers: Mapping[str, Iterable[str]] | None = None,
    free_route_accounts: Iterable[str] | None = None,
    frontier_workhorses: Iterable[str] | None = None,
    observed_failures: Iterable[Mapping[str, Any]] | None = None,
    now: float = 0.0,
    state_path: str | os.PathLike[str] | None = None,
) -> list[RankedModel]:
    """Rank every model we know about into the four tiers.

    The inventory is what we can use. The free model list and the 3D scores
    may mention a model the inventory does not offer; such a model is
    reported as unavailable and is never ranked.

    The quality of a model is the measured Artificial Analysis record and
    nothing else: a model without one has no quality and no tier, and the
    tiers carry no quality threshold calibrated on a guess. The 7 day token
    usage is accepted for the dashboard's own accounting and does not change
    a rank.

    `exclude_providers` names, per tier, the providers that must not appear
    in it. The default keeps every provider in every tier.

    `frontier_workhorses` is the owner's list of the models that may hold
    the frontier. It comes from the runtime policy; the constant is only the
    fallback for a caller that has no policy.

    `observed_failures` are the recent failures of the routes, read from
    the T3 Code state. A failure is scoped: to an account, to a route or
    to one model. A model under a failed scope is not available, and it
    stays visible: it is reported with the reason and the moment it was
    observed.
    """
    workhorses = tuple(
        str(name) for name in (frontier_workhorses or FRONTIER_WORKHORSES)
    )
    failures = _observed_failures(observed_failures)
    inventory: set[tuple[str, str]] = set()
    for record in models or ():
        pair = _record_pair(record)
        if pair:
            inventory.add(pair)

    free_pairs: set[tuple[str, str]] = set()
    for record in free_models or ():
        pair = _record_pair(record)
        if pair:
            free_pairs.add(pair)
    # The promotional zero-price models of a paid provider. They are not the
    # dedicated free routes: they are paid provider routes that cost nothing
    # right now, so they belong to bulk, strongly preferred.
    promo_pairs: set[tuple[str, str]] = set()
    for record in promo_models or ():
        pair = _record_pair(record)
        if pair and pair not in free_pairs:
            promo_pairs.add(pair)
    external = {
        pair: bool(value)
        for pair, value in (external_availability or {}).items()
        if isinstance(pair, tuple) and len(pair) == 2
    }

    three_d: dict[tuple[str, str], Any] = {}
    for key, entry in (three_d_scores or {}).items():
        pair = _record_pair(key)
        if pair:
            three_d[pair] = entry

    windows_by_account, windows_by_model = _quota_windows(quota_windows)
    excluded = _excluded_providers(exclude_providers)
    free_route_accounts = {str(account) for account in (free_route_accounts or ())}
    state = _load_state(state_path) if state_path else {}
    usage = {
        pair: float(value)
        for pair, value in (usage_tokens or {}).items()
        if isinstance(value, (int, float))
    }

    universe = inventory | free_pairs | set(three_d)

    candidates: list[_Candidate] = []
    for provider, model in sorted(universe):
        account = account_for(provider, model)
        observed_free_route = False
        # Every applicable limit gates the model: the shared account windows
        # that name it (or name no model) and its own model windows. A model
        # reading does not replace the shared cap; an unrelated family window
        # is excluded by its scope.
        parent_windows = [
            window
            for window in windows_by_account.get(account, [])
            if _window_applies(window, model)
        ]
        model_windows = list(windows_by_model.get((provider, model)) or [])
        # A route the provider publishes as unlimited is not gated by the
        # paid allowance of the account: the two are different entitlements.
        # The allowance windows that are exempted are counted, so the
        # decision stays visible instead of hiding the account's state.
        exempted: list[Any] = []
        if any(_is_unlimited_window(window) for window in model_windows):
            kept: list[Any] = []
            for window in parent_windows:
                if _is_allowance_window(window):
                    exempted.append(window)
                else:
                    kept.append(window)
            parent_windows = kept
        windows = parent_windows + model_windows
        # A promotional or free route is not exempt from its account's paid
        # allowance by price, a model suffix or an operation while the
        # allowance is spent. Only a scope the provider reports separates it;
        # the observation is recorded, never used to remove a measured window.
        observed_free_route = (
            (provider, model) in free_pairs or (provider, model) in promo_pairs
        ) and account in free_route_accounts
        detail = _capacity_detail(windows, now)
        remaining = detail["remaining"]
        expires_in = detail["expiresIn"]
        urgency = detail["urgency"]
        # An unknown capacity earns no advantage: it is not unlimited.
        capacity_bonus = (remaining or 0.0) * urgency
        # Being behind the pace of the window is an advantage: it spreads the
        # usage across the reset limits instead of piling it on one account.
        pace = detail["pace"]

        in_inventory = (provider, model) in inventory
        external_state = external.get((provider, model))
        # An observed failure of the T3 Code state: the route is not usable
        # now. The model stays visible, with the reason and the moment.
        native_instance = str(
            ((native_models or {}).get((provider, model)) or {}).get(
                "providerInstance"
            )
            or ""
        )
        failure = _failure_for(failures, account, native_instance, model)
        # The windows that constrain the route. A window a source publishes
        # without reading stays visible, but it does not gate: an unknown
        # reading is not evidence that an account is exhausted.
        gating_windows = [
            window for window in windows if getattr(window, "gating", True) is not False
        ]
        if failure is not None:
            # The T3 Code state says this route is broken right now. The
            # model is not usable, and it stays visible with the reason.
            available = False
            availability_reason = str(failure.get("label") or "") or REASON_ROUTE_FAILED
        elif external_state is False:
            # A source that watches the route says it is not usable now, for
            # example a cooling down pool route.
            available = False
            availability_reason = REASON_ROUTE_PARKED
        elif not gating_windows:
            # The provider reports no quota for this account, or only a
            # window it did not read. The model can still be used, but its
            # headroom is unknown, not unlimited.
            available = bool(in_inventory)
            availability_reason = (
                REASON_CAPACITY_UNKNOWN if available else REASON_NOT_OFFERED
            )
        else:
            # A window that is unknown, malformed, or stale makes the
            # headroom unknown, and unknown headroom is not usable headroom.
            available = bool(in_inventory) and (
                remaining is not None and remaining > MIN_REMAINING
            )
            if available:
                availability_reason = REASON_AVAILABLE
            elif not in_inventory:
                availability_reason = REASON_NOT_OFFERED
            elif remaining is None:
                availability_reason = REASON_CAPACITY_UNKNOWN
            else:
                availability_reason = REASON_CAPACITY_SPENT

        native_entry = (native_models or {}).get((provider, model)) or {}
        native_options = (
            native_entry.get("options") if isinstance(native_entry, Mapping) else None
        )
        quality = quality_score(
            aa_cache,
            provider,
            model,
            options=native_options,
        )
        # The value of the model under the owner's policy. It is the score
        # the tier order uses, so the published score is the number the
        # decision was made on.
        value = value_score(
            aa_cache,
            provider,
            model,
            options=native_options,
        )

        catalog_entry = _catalog_entry(catalog, provider, model)
        released = _release_epoch(catalog_entry)
        fresh = released is not None and (now - released) / DAY <= FRONTIER_MAX_AGE_DAYS

        family = catalog_entry.get("family")
        lineage = _lineage_key(family if isinstance(family, str) else "", model)

        three_d_score, three_d_tokens, three_d_eligible = _three_d_values(
            three_d.get((provider, model))
        )

        settled, pending_reason = _admission(
            provider,
            model,
            state,
            usage.get((provider, model), 0.0),
            released,
            now,
        )

        candidates.append(
            _Candidate(
                provider=provider,
                model=model,
                quality=quality,
                value=value,
                available=available,
                workhorses=workhorses,
                fresh=fresh,
                small=_has_size_marker(model),
                economy=_is_economy(catalog_entry, model),
                lineage=lineage,
                newness=_newness(released, model, provider),
                capacity_bonus=capacity_bonus,
                remaining=remaining,
                expires_in=expires_in,
                free=(provider, model) in free_pairs,
                three_d_score=three_d_score,
                three_d_tokens=three_d_tokens,
                three_d_eligible=three_d_eligible,
                settled=settled,
                pending_reason=pending_reason,
                used_tokens=usage.get((provider, model), 0.0),
                windows=list(windows),
                pace=detail["paceValue"] if detail["paceValue"] is not None else pace,
                expected=detail["paceExpected"] if detail["paceExpected"] is not None else detail["expected"],
                actual=detail["paceActual"] if detail["paceActual"] is not None else detail["actual"],
                pace_binding=detail["paceBinding"],
                capacity_binding=detail["binding"],
                account=account,
                quota_scope={
                    "account": account,
                    "parent_windows": len(parent_windows),
                    "model_windows": len(model_windows),
                    "windows": len(windows),
                    "observed_free_route": bool(observed_free_route),
                    "exemption": False,
                    "basis": (
                        "every applicable limit gates the model: the shared "
                        "account windows and its own model windows; price and "
                        "a model suffix do not exempt a route"
                    ),
                },
                frontier_surplus=_frontier_surplus(list(windows), now),
                applied_windows=list(windows),
                unlimited=any(_is_unlimited_window(window) for window in model_windows),
                availability_reason=availability_reason,
            )
        )

    # The frontier belongs to the newest model of every lineage.
    frontier_keys = _frontier_winners(candidates)
    # The 3D tier holds the models that are worth using for 3D work.
    three_d_keys = {
        candidate.key
        for candidate in candidates
        # Explicit visual capability and a verified workload admission put a
        # model in the tier; a measured record lets it hold a rank. Nothing
        # else does: no family prior, no token volume, no attachment.
        if candidate.available and candidate.three_d_eligible and candidate.three_d_score > 0.0
    }

    entries: list[RankedModel] = []
    for candidate in candidates:
        provider = candidate.provider
        model = candidate.model
        quality = candidate.quality

        tiers: list[str] = []
        if candidate.key in frontier_keys:
            tiers.append("frontier")
        surplus = candidate.frontier_surplus
        # A tier holds a model on its measured value. A model without one has
        # no value, so it is not ranked: the score of a tier is the value,
        # and a tier of values nobody measured is not a ranking.
        if (
            candidate.available
            and candidate.value is not None
            and (
                "frontier" not in tiers
                # A frontier model may carry volume work when an allowance
                # of its own resets within a day and the review capacity is
                # not under pressure. The surplus never empties the review
                # capacity early.
                or bool(surplus.get("available"))
            )
        ):
            tiers.append("bulk")
        if candidate.available and candidate.free and candidate.value is not None:
            tiers.append("free")
        if candidate.key in three_d_keys:
            tiers.append("3d")

        scores: dict[str, float] = {}
        # The published score of a model is its measured value. Nothing else
        # is in it: no name suffix, no catalog price, no capacity term and
        # no pace term. A tier orders the candidates of one provider by this
        # value, and the providers are ordered by their pace; blending a
        # guess into the score would make the published number disagree
        # with the decision it claims to explain.
        for tier in tiers:
            if tier == "3d":
                # The tier ranks the measured AA-3D Elo, with its source,
                # date and conditions published. It does not rank a prior, the
                # general intelligence index, or token volume.
                scores[tier] = candidate.three_d_score
            else:
                scores[tier] = candidate.value if candidate.value is not None else 0.0

        if not tiers:
            entries.append(
                RankedModel(
                    tier="",
                    provider=provider,
                    model=model,
                    rank=0,
                    score=0.0,
                    quality=quality,
                    remaining=candidate.remaining,
                    expires_in_seconds=candidate.expires_in,
                    available=candidate.available,
                    reasons=tuple(_reasons(candidate, "")),
                    windows=tuple(candidate.windows),
                    settled=candidate.settled,
                    account=candidate.account,
                    pace=candidate.pace,
                    pace_binding=candidate.pace_binding,
                    capacity_binding=candidate.capacity_binding,
                    applied_windows=tuple(candidate.applied_windows),
                    frontier_surplus=candidate.frontier_surplus,
                    quota_scope=candidate.quota_scope,
                    pending_reason=candidate.pending_reason,
                    used_tokens=candidate.used_tokens,
                    three_d_tokens=candidate.three_d_tokens,
                    observed_failure=dict(failure or {}),
                    unlimited=candidate.unlimited,
                    availability_reason=candidate.availability_reason,
                )
            )
            continue

        tier_entries: list[RankedModel] = []
        for tier in tiers:
            if provider.strip().lower() in excluded.get(tier, ()):
                continue
            tier_entries.append(
                RankedModel(
                    tier=tier,
                    provider=provider,
                    model=model,
                    rank=0,
                    score=scores[tier],
                    quality=quality,
                    remaining=candidate.remaining,
                    expires_in_seconds=candidate.expires_in,
                    available=candidate.available,
                    reasons=tuple(_reasons(candidate, "")),
                    windows=tuple(candidate.windows),
                    settled=candidate.settled,
                    account=candidate.account,
                    pace=candidate.pace,
                    pace_binding=candidate.pace_binding,
                    capacity_binding=candidate.capacity_binding,
                    applied_windows=tuple(candidate.applied_windows),
                    frontier_surplus=candidate.frontier_surplus,
                    quota_scope=candidate.quota_scope,
                    pending_reason=candidate.pending_reason,
                    used_tokens=candidate.used_tokens,
                    three_d_tokens=candidate.three_d_tokens,
                    observed_failure=dict(failure or {}),
                    unlimited=candidate.unlimited,
                    availability_reason=candidate.availability_reason,
                )
            )
        if not tier_entries:
            # Every tier of this model is closed to its provider; the model
            # is still reported, it just holds no rank.
            tier_entries.append(
                RankedModel(
                    tier="",
                    provider=provider,
                    model=model,
                    rank=0,
                    score=0.0,
                    quality=quality,
                    remaining=candidate.remaining,
                    expires_in_seconds=candidate.expires_in,
                    available=candidate.available,
                    reasons=tuple(_reasons(candidate, "")),
                    windows=tuple(candidate.windows),
                    settled=candidate.settled,
                    account=candidate.account,
                    pace=candidate.pace,
                    pace_binding=candidate.pace_binding,
                    capacity_binding=candidate.capacity_binding,
                    applied_windows=tuple(candidate.applied_windows),
                    frontier_surplus=candidate.frontier_surplus,
                    quota_scope=candidate.quota_scope,
                    pending_reason=candidate.pending_reason,
                    used_tokens=candidate.used_tokens,
                    three_d_tokens=candidate.three_d_tokens,
                    observed_failure=dict(failure or {}),
                    unlimited=candidate.unlimited,
                    availability_reason=candidate.availability_reason,
                )
            )
        entries.extend(tier_entries)

    ranked: list[RankedModel] = []
    for tier in TIERS:
        members = [entry for entry in entries if entry.tier == tier and entry.available]
        # Inside one provider the measured value decides, and across the
        # providers the pace of their own window does. The capacity is
        # reported beside the rank, but it never orders the tier: an
        # allowance that frees up soon is not a capability.
        members.sort(
            key=lambda entry: (
                -entry.score,
                -(entry.pace if entry.pace is not None else 0.0),
                entry.provider,
                entry.model,
            )
        )
        if tier == "3d":
            # The 3D tier stays small: only the best models are worth
            # printing with. The models that do not fit are still reported.
            for entry in members[THREE_D_MAX_MEMBERS:]:
                entry.tier = ""
                entry.rank = 0
            members = members[:THREE_D_MAX_MEMBERS]
        for position, entry in enumerate(members, start=1):
            entry.rank = position
            ranked.append(entry)
    ranked.extend(
        sorted(
            (entry for entry in entries if not entry.tier),
            key=lambda entry: (entry.provider, entry.model),
        )
    )

    if state_path:
        state = _update_state(
            _load_state(state_path), {_state_key(p, m) for p, m in universe}, now
        )
        _save_state(state_path, state)

    return ranked


def rank_samples(
    ranked: list[RankedModel], *, now: float
) -> list[tuple[str, dict[str, str], float]]:
    """Render the ranking as Prometheus samples.

    Every ranked model is published, including the ones that cannot be used
    right now: an unavailable or exhausted model keeps its capacity series
    (zero when the allowance is spent), its availability with the reason it
    is not usable, and its rank. A consumer can therefore list a model that
    is not offered at the bottom of a tier with the reason beside it. Only
    the winners are allowed to exclude a model.
    """
    samples: list[tuple[str, dict[str, str], float]] = []
    seen: set[tuple[str, str]] = set()

    for entry in ranked:
        provider = label_value(entry.provider)
        model = label_value(entry.model)
        tier = label_value(entry.tier)
        key = (provider, model)
        if key not in seen:
            seen.add(key)
            labels = {"provider": provider, "model": model}
            if entry.quality is not None:
                # A model without a measured record has no quality sample at
                # all; a zero or a prior would be a claim.
                samples.append(
                    ("ghostship_ai_model_quality", dict(labels), float(entry.quality))
                )
            samples.append(
                (
                    "ghostship_ai_model_available",
                    {
                        **labels,
                        # The reason the model is not usable, or an empty
                        # string when it is. It is a fixed label, never the
                        # provider's own text.
                        "reason": label_value(entry.availability_reason),
                    },
                    1.0 if entry.available else 0.0,
                )
            )
            if entry.remaining is not None:
                # An unknown capacity is not reported as zero or as unlimited.
                # A spent allowance is reported as zero.
                samples.append(
                    (
                        "ghostship_ai_model_capacity_remaining",
                        {**labels, "tier": tier},
                        float(entry.remaining),
                    )
                )
            if entry.expires_in_seconds is not None:
                samples.append(
                    (
                        "ghostship_ai_model_capacity_expires_in_seconds",
                        {**labels, "tier": tier},
                        float(entry.expires_in_seconds),
                    )
                )
            samples.append(
                (
                    "ghostship_ai_model_evaluated_timestamp_seconds",
                    dict(labels),
                    float(now),
                )
            )
            # Why the headroom of this model is unknown. An unknown headroom
            # always says why, so the dashboard never shows a bare
            # "unknown".
            reason = (
                ""
                if quota_module is None
                else quota_module.unknown_reason_code(entry.windows, entry.remaining)
            )
            if reason:
                samples.append(
                    (
                        "ghostship_ai_model_quota_unknown",
                        {**labels, "reason": reason},
                        1.0,
                    )
                )
        # The rank of every model, including the ones that hold no tier: a
        # model that is not usable stays visible with its rank.
        samples.append(
            (
                "ghostship_ai_model_rank",
                {"tier": tier, "provider": provider, "model": model},
                float(entry.rank),
            )
        )
        if not entry.tier or not entry.available:
            continue
        tier_labels = {"tier": tier, "provider": provider, "model": model}
        samples.append(("ghostship_ai_model_score", dict(tier_labels), float(entry.score)))
        samples.append(
            (
                "ghostship_ai_model_tier",
                {"provider": provider, "model": model, "tier": tier},
                1.0,
            )
        )
    return samples
