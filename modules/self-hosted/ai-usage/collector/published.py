"""The limits the providers publish, with the evidence that they publish them.

A published number is not a measurement. It is what a provider's own
documentation says, with the source that says it and the date it was read.
The collector uses a published number only where the provider reports no
reading of its own, and it marks every window it builds from one, so a
reader never mistakes a published limit for a provider's own answer.

The OpenCode Go documentation lists the free Go routes as unlimited:

    Each model has the following usage limits: 5-hour - 20% of the monthly
    limit; weekly - 50%; and monthly - 100%.

and, for the free routes, "Requests per 5 hours / week / month: Unlimited",
with "If you reach the usage limit, you can continue using the free
models." A live probe confirmed it: a free route answered while the paid
monthly window of the plan was at 100% used, and the paid route of the same
provider did not.

The same documentation says the free models are unlimited "for a limited
time". That is a promotion with no published end date, not a permanent
entitlement: the basis of those routes is `promotion`, the end of the
promotion is unknown, and the window says so. A promotion may end without
notice, and the collector publishes the state it has, not a promise about
the future.

The OpenRouter documentation publishes the rate limits of the free models:
20 requests a minute, and a daily allowance that depends on the balance of
the account.
"""

from __future__ import annotations

# The OpenCode Go provider account and the routes its documentation lists as
# unlimited.
GO_PROVIDER = "opencode-go"
GO_FREE_SUFFIX = "-free"
GO_DOCS_SOURCE = "https://opencode.ai/docs/go/"
GO_DOCS_CHECKED_AT = "2026-10-22"

# The basis of the free routes: the documentation lists them as unlimited
# "for a limited time", so the basis is a promotion and not a permanent
# entitlement.
GO_FREE_BASIS = "promotion"

# The end of the promotion. The documentation publishes no date, so the end
# is unknown: it is never a guess and never a zero.
GO_FREE_ENDS_AT = None

# The label the dashboard shows for those routes.
GO_FREE_LABEL = "unlimited (limited-time promotion)"

# The OpenRouter published rate limits of the free models.
OPENROUTER_LIMITS_SOURCE = "https://openrouter.ai/docs/api-reference/limits"
OPENROUTER_LIMITS_CHECKED_AT = "2026-10-22"
OPENROUTER_FREE_REQUESTS_PER_MINUTE = 20

# The quota id of the window that states a route is published as unlimited.
UNLIMITED_QUOTA_ID = "free-unlimited"


def unlimited_route(provider: str, model: str) -> bool:
    """True when the provider publishes this route as unlimited.

    The Go documentation names its free routes by the `-free` suffix and
    lists them as unlimited. The rule is the published one, not a guess
    about a price: a route that costs nothing because of a promotion is a
    different thing.
    """
    if str(provider or "") != GO_PROVIDER:
        return False
    return str(model or "").lower().endswith(GO_FREE_SUFFIX)
