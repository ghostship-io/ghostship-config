"""The limits the free pool's providers publish.

The pool enforces its own ceilings on every provider it drives. Those
ceilings are a local policy, not the provider's allowance, and they are
published with the basis "configured". This module carries the
independent reading: what the provider itself documents.

Every number here was read from the provider's own documentation on the
date below, and the source of each provider is kept beside its numbers.
A limit the provider documents but publishes no number for is published
with the basis "unknown" and the value -1: the limit exists, its
number does not, and the two are not the same statement.

Nothing here is a measurement. The pool's ceilings and the headers it
sees are read at collection time; this table only says what the provider
documents, and when it was read.
"""

from __future__ import annotations

# The day the provider documentation was read.
PUBLISHED_CHECKED_AT = "2026-10-22"

# The source of every published number: the provider's own documentation.
PUBLISHED_SOURCE = "provider documentation"

# The value published for a limit whose number the provider does not
# publish. It is a sentinel, not a measurement.
UNKNOWN_LIMIT_VALUE = -1.0

# The published limits of every provider, with the source they came from.
PUBLISHED_LIMITS: dict[str, dict[str, object]] = {
    "cloudflare-workers-ai": {
        "url": 'https://developers.cloudflare.com/workers-ai/platform/pricing/',
        "checked_at": '2026-10-22',
        "limits": {'neurons_day': 10000},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "cohere": {
        "url": 'https://docs.cohere.com/docs/rate-limits',
        "checked_at": '2026-10-22',
        "limits": {'rpm': 20, 'rmonthly': 1000},
        "documented_without_number": ['rpd', 'tpd', 'tpm'],
    },
    "github-models": {
        "url": 'https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models#rate-limits',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "google": {
        "url": 'https://ai.google.dev/gemini-api/docs/rate-limits',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "groq": {
        "url": 'https://console.groq.com/docs/rate-limits',
        "checked_at": '2026-10-22',
        "limits": {'rpm': 30, 'rpd': 1000, 'tpm': 8000, 'tpd': 200000},
        "documented_without_number": [],
    },
    "huggingface": {
        "url": 'https://huggingface.co/docs/inference-providers/pricing',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "inception": {
        "url": 'https://docs.inceptionlabs.ai/get-started/rate-limits',
        "checked_at": '2026-10-22',
        "limits": {'rpm': 1000, 'input_tpm': 1000000, 'output_tpm': 100000},
        "documented_without_number": ['rpd', 'tpd', 'tpm'],
    },
    "kilo": {
        "url": 'https://kilo.ai/docs/gateway/usage-and-billing',
        "checked_at": '2026-10-22',
        "limits": {'rph': 200},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "mistral": {
        "url": 'https://docs.mistral.ai/admin/billing-usage/usage-limits',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "nvidia": {
        "url": 'https://docs.api.nvidia.com/nim/docs/product.md',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "opencode": {
        "url": 'https://docs.opencode.ai/docs/zen/',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "openrouter": {
        "url": 'https://openrouter.ai/docs/api-reference/limits',
        "checked_at": '2026-10-22',
        "limits": {'rpm': 20, 'rpd': 50, 'rpd_with_10_credits': 1000},
        "documented_without_number": ['tpd', 'tpm'],
    },
    "orcarouter": {
        "url": 'https://www.orcarouter.ai/models?price=free',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "poolside": {
        "url": 'https://docs.poolside.ai/',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "requesty": {
        "url": 'https://docs.requesty.ai/features/in-flight-rate-limits.md',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "upstage": {
        "url": 'https://console.upstage.ai/docs/guides/rate-limits',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "vercel": {
        "url": 'https://vercel.com/docs/ai-gateway/pricing',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
    "zai": {
        "url": 'https://docs.z.ai/guides/overview/pricing',
        "checked_at": '2026-10-22',
        "limits": {},
        "documented_without_number": ['rpd', 'rpm', 'tpd', 'tpm'],
    },
}


def published_limits(provider: str) -> list[tuple[str, float, str]]:
    """The published limits of one provider, with the basis of each.

    A documented limit without a published number is reported with the
    basis "unknown" and the sentinel value, so a reader can tell
    "the provider publishes nothing" from "the provider publishes no
    number".
    """
    entry = PUBLISHED_LIMITS.get(str(provider or "")) or {}
    found: list[tuple[str, float, str]] = []
    for name, value in sorted((entry.get("limits") or {}).items()):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found.append((str(name), float(value), "published"))
    for name in entry.get("documented_without_number") or ():
        found.append((str(name), UNKNOWN_LIMIT_VALUE, "unknown"))
    return found
