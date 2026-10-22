"""The free pool's providers, and the limits they publish.

The free inference pool enforces its own ceilings on every provider it
drives. Those ceilings are a local policy, not the provider's allowance, so
they are published with the basis "configured". The provider's own
documentation is a second, independent reading, published with the basis
"published", and what the provider's response headers said is a third, with
the basis "observed".

This module carries the published reading. It was read from the providers'
own documentation on the date below, and every number here is the number the
provider published:

* a number means the provider publishes that limit;
* ``None`` means the provider documents the limit but publishes no number
  for it, which is published with the basis "unknown" and the value -1.

Nothing here is a measurement: the pool's own ceilings and the headers it
sees are read at collection time. This table only says what the provider
documents, and when it was read.
"""

from __future__ import annotations

# The day the provider documentation was read.
PUBLISHED_CHECKED_AT = "2026-10-22"

# The source of every number: the provider's own documentation.
PUBLISHED_SOURCE = "provider documentation"

# The limits each provider documents, and the number it publishes for them.
# A None value is a documented limit without a published number.
PUBLISHED_LIMITS: dict[str, dict[str, float | None]] = {
    "cloudflare-workers-ai": {
        "neurons_day": 10000.0,
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "cohere": {
        "rpm": 20.0,
        "rmonthly": 1000.0,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "github-models": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "google": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "groq": {
        "rpm": 30.0,
        "rpd": 1000.0,
        "tpm": 8000.0,
        "tpd": 200000.0,
    },
    "huggingface": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "inception": {
        "rpm": 1000.0,
        "input_tpm": 1000000.0,
        "output_tpm": 100000.0,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "kilo": {
        "rpm": None,
        "rph": 200.0,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "mistral": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "nvidia": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "opencode": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "openrouter": {
        "rpm": 20.0,
        "rpd": 50.0,
        "rpd_with_10_credits": 1000.0,
        "tpm": None,
        "tpd": None,
    },
    "orcarouter": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "poolside": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "requesty": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "upstage": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "vercel": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
    "zai": {
        "rpm": None,
        "rpd": None,
        "tpm": None,
        "tpd": None,
    },
}

# The value published for a limit whose number the provider does not publish.
# It is a sentinel, not a measurement: the limit exists, its number does not.
UNKNOWN_LIMIT_VALUE = -1.0


def published_limits(provider: str) -> dict[str, float]:
    """The published limits of one provider, with their basis.

    A documented limit without a published number is reported with the
    basis "unknown" and the sentinel value, so a reader can tell "the
    provider publishes nothing" from "the provider publishes no number".
    """
    found: dict[str, float] = {}
    for name, value in (PUBLISHED_LIMITS.get(str(provider or "")) or {}).items():
        if value is None:
            found[name] = UNKNOWN_LIMIT_VALUE
        else:
            found[name] = float(value)
    return found
