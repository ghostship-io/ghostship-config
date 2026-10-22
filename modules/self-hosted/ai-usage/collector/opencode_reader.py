"""Read OpenCode's request records into usage events.

OpenCode records every model request in its own SQLite database: the
provider, the model, the tokens, the time, and, when the request failed, the
provider's own error. This module turns those records into the events the AI
usage collector infers a route's window and budget from.

The owner rule is in ghostship-agent's `config/agents/routing-policy.md`,
"Usage measurement": only a budget limit forms an episode. A concurrency
refusal, a per-minute refusal, a transient upstream refusal, a request that
was too large, an expired key and an aborted run spend no window, so they are
read as `other` and never as a limit.

The text of a provider's error is read in memory to pick the outcome. It is
never stored, never returned and never logged. A real limit message names the
account it belongs to, and that name stays in the process.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

# The three outcomes of a request.
OUTCOME_SUCCESS = "success"
OUTCOME_LIMIT = "limit"
OUTCOME_OTHER = "other"

OUTCOMES = (OUTCOME_SUCCESS, OUTCOME_LIMIT, OUTCOME_OTHER)

# The window hints a failure may name. The inference uses the window the
# error names when it names one, and the timing estimate otherwise.
WINDOW_1M = "1m"
WINDOW_1H = "1h"
WINDOW_5H = "5h"
WINDOW_1D = "1d"
WINDOW_7D = "7d"
WINDOW_30D = "30d"

WINDOWS = (WINDOW_1M, WINDOW_1H, WINDOW_5H, WINDOW_1D, WINDOW_7D, WINDOW_30D)

# The finishes that mean the request completed. A request that stopped for
# one of these reasons used its budget and is a success, whatever the
# provider called the stop.
SUCCESS_FINISHES = frozenset({"stop", "tool-calls", "length", "content-filter"})

# The phrases that name a budget, and the window each one names. The order
# matters: the phrase that names its window is read before the phrase that
# names only a budget.
_BUDGET_PHRASES = (
    (("session usage limit",), WINDOW_5H),
    (("weekly usage limit",), WINDOW_7D),
    (("exceeded your current quota", "current quota"), None),
    (
        ("daily limit reached", "limit_rpd", "free-models-per-day"),
        WINDOW_1D,
    ),
    (("requires a positive account balance", "positive account balance"), None),
    (("requires a valid credit card", "valid credit card"), None),
    (("usage limit",), None),
)

# The refusals that are never a budget failure. They are read before the
# budget phrases: a concurrency refusal, a per-minute refusal and a
# transient upstream refusal all say "limit", and none of them spends a
# window.
_NEVER_LIMIT_PHRASES = (
    "too many concurrent requests",
    "concurrent request",
    "worker local total request limit",
    "free-models-per-min",
    "per minute",
    "per-minute",
    "tokens per minute",
    "request too large",
    "upstream",
    "api key has expired",
    "authentication token is invalid",
    "invalid api key",
    "unauthorized",
    "step interrupted",
    "timed out waiting for response headers",
    "timed out",
    "timeout",
    "provider returned error",
)

# The error types that are never a budget failure either, whatever the
# provider's own words say.
_NEVER_LIMIT_TYPES = ("abort", "timeout", "auth")

# The error type that states the request was refused against the account's
# allowance.
QUOTA_TYPES = frozenset({"provider.quota"})

# The words that make a quota refusal a budget refusal. Without one of them
# the refusal is not about the account's allowance.
_BUDGET_WORDS = ("rate limit", "quota", "usage limit", "limit exceeded")

_SPACES = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Lower-case the text and collapse its whitespace."""
    return _SPACES.sub(" ", str(text or "")).strip().lower()


def error_message(error: Mapping[str, Any]) -> str:
    """The provider's own words for a failure, or an empty string.

    The text is read in memory and never leaves this module.
    """
    if not isinstance(error, Mapping):
        return ""
    data = error.get("data")
    message = ""
    if isinstance(data, Mapping):
        candidate = data.get("message")
        if not candidate:
            candidate = data.get("error")
        if isinstance(candidate, str):
            message = candidate
    elif isinstance(data, str):
        message = data
    if not message:
        candidate = error.get("message")
        if isinstance(candidate, str):
            message = candidate
    return message


def _budget_window(message: str) -> tuple[bool, str | None]:
    """The window a message names, if it names a budget at all.

    The first element says whether the message is a budget refusal; the
    second is the window it names, or None when it names none.
    """
    text = _normalise(message)
    if not text:
        return (False, None)
    for phrases, window in _BUDGET_PHRASES:
        if any(phrase in text for phrase in phrases):
            return (True, window)
    return (False, None)


def _never_limit(message: str, kind: str) -> bool:
    """True when the refusal spends no window."""
    lowered = _normalise(kind)
    if any(marker in lowered for marker in _NEVER_LIMIT_TYPES):
        return True
    text = _normalise(message)
    if not text:
        return False
    return any(phrase in text for phrase in _NEVER_LIMIT_PHRASES)


def classify_error(error: Mapping[str, Any]) -> tuple[str, str | None]:
    """The outcome of a failed request, and the window it names."""
    kind = str(error.get("type") or "").strip().lower() if isinstance(error, Mapping) else ""
    message = error_message(error)
    if _never_limit(message, kind):
        return (OUTCOME_OTHER, None)
    matched, window = _budget_window(message)
    if matched:
        return (OUTCOME_LIMIT, window)
    text = _normalise(message)
    if kind in QUOTA_TYPES and any(word in text for word in _BUDGET_WORDS):
        # The provider refused against the account's allowance and said so.
        return (OUTCOME_LIMIT, None)
    return (OUTCOME_OTHER, None)


def classify(data: Mapping[str, Any]) -> tuple[str, str | None]:
    """The outcome of a request record, and the window it names."""
    if not isinstance(data, Mapping):
        return (OUTCOME_OTHER, None)
    error = data.get("error")
    if not isinstance(error, Mapping) or not error:
        finish = str(data.get("finish") or "").strip().lower()
        if finish in SUCCESS_FINISHES:
            return (OUTCOME_SUCCESS, None)
        # No error and no finish: the record does not say the request ran.
        return (OUTCOME_OTHER, None)
    return classify_error(error)


def usage_tokens(data: Mapping[str, Any]) -> int | None:
    """The tokens a request used, or None when the record has none.

    The count is the input, output and reasoning tokens. A record without a
    tokens object has no usage to report, and None says so; a record with a
    tokens object of zeros has used nothing and reports zero.
    """
    if not isinstance(data, Mapping):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, Mapping):
        return None
    total = 0
    for key in ("input", "output", "reasoning"):
        value = tokens.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        total += int(value)
    return total
