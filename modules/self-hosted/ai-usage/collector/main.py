"""Collect AI provider usage, limits, and free models into Prometheus metrics.

The collector is read-only. It reads T3 Code's own readings, the provider
APIs T3 Code does not read, the free inference pool, and the public model
catalog, and writes one textfile for node_exporter.

Nothing here starts, stops, or reconfigures a provider, a container, or T3
Code itself.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aa  # noqa: E402
import aa_3d  # noqa: E402
import catalog as catalog_module  # noqa: E402
import codes  # noqa: E402
import pool as pool_module  # noqa: E402
import pool_published  # noqa: E402
import published as published_module  # noqa: E402
import quota as quota_module  # noqa: E402
import providers as providers_module  # noqa: E402
import ranking as ranking_module  # noqa: E402
import runtime_state as runtime_state_module  # noqa: E402
import snapshot as snapshot_module  # noqa: E402
import t3source  # noqa: E402
import threed as threed_module  # noqa: E402
from metrics import MetricWriter, Sample, SourceResult  # noqa: E402
from t3client import T3Client, T3Error  # noqa: E402
from util import now as wall_clock  # noqa: E402

T3_HOME = "/srv/apps/t3code/home"
T3_SERVER_FILE = "/run/ghostship-integrations/t3-server.json"
T3_SESSION_FILE = f"{T3_HOME}/.t3code-container/access/session.json"
SECRETS_ENV_FILE = "/run/ghostship-secrets/t3code.env"
POOL_SERVER_FILE = "/run/ghostship-integrations/inference-server.json"
POOL_TOKEN_FILE = "/run/ghostship-integrations/inference-token"
POOL_LEDGER_FILE = f"{T3_HOME}/.local/state/ghostship-agent/runtime/jobs.sqlite"
# The T3 Code state, read only. It carries the observed failures of the
# routes: a child that could not start, a provider that reported its
# allowance spent, a model that was refused.
T3_STATE_FILE = f"{T3_HOME}/.t3/userdata/statev2.sqlite"
CATALOG_FILE = f"{T3_HOME}/.cache/opencode/models.json"
# The smallest 3D prior that earns a place in the 3D tier.

# The owner's direction for the agents that run in this environment. It is a
# policy, not a measurement, and it never changes a provider reading.
OWNER_POLICY = {
    "frontierPrimeModels": ("claude-opus-5-5", "gpt-6.1-sol"),
    "allowedGptModels": ("gpt-6.1-sol",),
    "backgroundProviderInstances": ("opencode",),
    # The models the owner excludes from every selection. They stay visible
    # in the usage and the quota readings; they are never a winner and never
    # a recommendation.
    "excludedModels": ("gpt-6-astra", "claude-fable-5", "claude-fable-5-1"),
    # The frontier authority reviews every implementation before it is
    # integrated. A review by a bulk model is never a final approval, and a
    # required frontier that is unavailable is waited for, never replaced.
    "frontierReviewAuthority": {
        "provider_instance_id": "codex",
        "model_id": "gpt-6.1-sol",
    },
    "basis": "owner direction, 2026-10-21",
}

# The routing snapshot a consumer reads. The producer writes it; a consumer
# only reads it. It is separate from the internal ranking state.
SNAPSHOT_PATH = "/var/lib/ghostship-ai-usage/routing.json"

# The cached Artificial Analysis feed. The daily procedure reads the feed and
# writes the cache; the collector only reads the cache, so the free request
# budget belongs to one place.
AA_CACHE_PATH = "/var/lib/ghostship-ai-usage/artificial-analysis.json"

# The AA-3D board, written by the same pull of the public pages. Without
# the board there is no 3D rank: the 3D tier stays empty and the models
# that qualify for it are not reserved.
AA_3D_CACHE_PATH = "/var/lib/ghostship-ai-usage/aa-3d.json"

# The durable facts of the models, written by the daily procedure.
FACTS_PATH = "/var/lib/ghostship-ai-usage/facts.json"

# Every account the dashboard covers, and where its readings come from.
# A provider without a reader still gets a row, so nothing disappears.
COVERAGE = (
    ("codex", "t3"),
    ("claude", "t3"),
    ("grok", "grok"),
    ("antigravity", "antigravity"),
    ("opencode-go", "opencode-go"),
    ("openrouter", "openrouter"),
    ("ollama", "ollama"),
    ("opencode", "t3_usage"),
    ("cursor", "t3"),
    ("pi", "t3_usage"),
)

METRIC_HELP = {
    "ghostship_ai_source_success": "Whether the last collection of this source succeeded.",
    "ghostship_ai_source_status": "One for the current status of a source.",
    "ghostship_ai_provider_status": "One for the current state of a provider account.",
    "ghostship_ai_source_last_success_timestamp_seconds": "When a source last produced a reading.",
    "ghostship_ai_source_observed_timestamp_seconds": "When the reported reading was observed.",
    "ghostship_ai_source_duration_seconds": "How long a source took to read.",
    "ghostship_ai_quota_used_ratio": "Used share of a subscription or quota window.",
    "ghostship_ai_quota_reset_timestamp_seconds": "When a quota window resets.",
    "ghostship_ai_quota_observed_timestamp_seconds": "When a quota reading was observed.",
    "ghostship_ai_quota_state": "One for the state a provider reports for a window.",
    "ghostship_ai_quota_entitlement": (
        "One for every reading of a quota entitlement; a verified alias of "
        "the same window shares the entitlement id and keeps its own source."
    ),
    "ghostship_ai_entitlement_info": (
        "One for one canonical display reading per entitlement, even when no "
        "numeric reading is usable. The labels carry the basis of the "
        "numbers and the end of the entitlement, which is empty when the "
        "provider publishes none."
    ),
    "ghostship_ai_entitlement_used_ratio": (
        "The used share of the canonical reading of an entitlement."
    ),
    "ghostship_ai_entitlement_reset_timestamp_seconds": (
        "When the canonical reading of an entitlement resets."
    ),
    "ghostship_ai_entitlement_expected_used_ratio": (
        "The even-spend line of the canonical reading of an entitlement."
    ),
    "ghostship_ai_entitlement_pace_delta_ratio": (
        "The canonical reading's expected minus measured share."
    ),
    "ghostship_ai_entitlement_observed_timestamp_seconds": (
        "When the canonical reading of an entitlement was observed."
    ),
    "ghostship_ai_account_amount": "Reported balance, usage, cap, or request count.",
    "ghostship_ai_account_flag": "One for a reported account flag.",
    "ghostship_ai_account_observed_timestamp_seconds": "When an account reading was observed.",
    "ghostship_ai_usage_tokens": "Tokens used, by kind and window.",
    "ghostship_ai_usage_cost_usd": "Cost in US dollars, by basis and window.",
    "ghostship_ai_usage_unpriced_records": "Records that no price could be found for.",
    "ghostship_ai_usage_observed_timestamp_seconds": "When usage was observed.",
    "ghostship_ai_free_model": "One for a model that can be used at no cost.",
    "ghostship_ai_free_model_available": "Whether a free model can be selected now.",
    "ghostship_ai_free_model_price_usd_per_mtok": "The catalog price of a free model.",
    "ghostship_ai_free_model_observed_timestamp_seconds": "When the free model list was read.",
    "ghostship_ai_pool_model_info": "One for a model the free pool may use.",
    "ghostship_ai_pool_model_available": "Whether a pool model is available now.",
    "ghostship_ai_pool_model_selected": "Whether a pool model is the selected one.",
    "ghostship_ai_pool_model_cooldown_until_seconds": "When a pool model's cooldown ends.",
    "ghostship_ai_pool_model_admission": "Whether a pool model is admitted for a workload.",
    "ghostship_ai_pool_limit": "A local admission limit of the free pool.",
    "ghostship_ai_pool_observed_limit": (
        "A limit the provider's own response headers carried, as observed."
    ),
    "ghostship_ai_pool_published_limit": (
        "A limit the provider itself publishes, with the source it was read "
        "from."
    ),
    "ghostship_ai_provider_limit": (
        "A limit of a free provider, with the basis it was read with: "
        "published, configured, observed or unknown."
    ),
    "ghostship_ai_pool_cooldown_invalid": (
        "One for a cooldown of a pool route that cannot be true; the route is "
        "not blocked by it."
    ),
    "ghostship_ai_pool_admission": (
        "Whether a pool route is admitted for a workload, with the score the "
        "pool's own bench gave it."
    ),
    "ghostship_ai_pool_provider_state": "One for the current state of a pool provider.",
    "ghostship_ai_pool_health_events": "Successes and failures recorded for a pool model.",
    "ghostship_ai_pool_latency_seconds": "Observed latency of a pool model.",
    "ghostship_ai_pool_concurrency": "Current and allowed concurrency of a pool provider.",
    "ghostship_ai_pool_recent_jobs": "One for a recent job in the free pool.",
    "ghostship_ai_pool_quota_amount": "A quota amount observed in provider response headers.",
    "ghostship_ai_pool_quota_reset_seconds": "When an observed quota resets.",
    "ghostship_ai_pool_quota_observed_timestamp_seconds": "When an observed quota was seen.",
    "ghostship_ai_pool_ledger_requests": "Requests the free pool reserved over a window.",
    "ghostship_ai_pool_catalog_updated_timestamp_seconds": "When the pool catalog was refreshed.",
    "ghostship_ai_provider_coverage": "One for every provider the dashboard covers.",
    "ghostship_ai_route_unavailable": (
        "One for a route the T3 Code state says is unavailable, with the "
        "scope of the failure and the reason code."
    ),
    "ghostship_ai_route_unavailable_observed_timestamp_seconds": (
        "When the T3 Code state observed the failure of a route."
    ),
    "ghostship_ai_model_rank": "The rank of a model inside a tier, 1 is best.",
    "ghostship_ai_model_score": "The ranking score of a model inside a tier.",
    "ghostship_ai_model_quality": "The quality score of a model.",
    "ghostship_ai_model_available": (
        "Whether a model can be used right now, with the reason it cannot."
    ),
    "ghostship_ai_model_capacity_remaining": (
        "The remaining share of a model's account capacity, zero when it is spent."
    ),
    "ghostship_ai_model_quota_unknown": (
        "One for a model whose headroom is unknown, with the reason it is unknown."
    ),
    "ghostship_ai_model_capacity_expires_in_seconds": "When the model's account capacity expires.",
    "ghostship_ai_model_tier": "One for every tier a model belongs to.",
    "ghostship_ai_model_evaluated_timestamp_seconds": "When a model was last evaluated.",
    "ghostship_ai_three_d_usage_tokens": "Tokens spent on 3D printing work.",
    # The two series below are no longer emitted: the 3D prior and its blended
    # score were a judgement, and the owner removed them. They stay declared
    # so a dashboard that still queries them shows no data, not an error.
    "ghostship_ai_three_d_prior": "Removed: no 3D prior is published.",
    "ghostship_ai_three_d_score": "Removed: no blended 3D score is published.",
    "ghostship_ai_three_d_observed_timestamp_seconds": "When the 3D reading was taken.",
    "ghostship_ai_model_strength": (
        "The verified Artificial Analysis intelligence index of the model; a "
        "model without a record has no strength and is unranked."
    ),
    "ghostship_ai_model_relative_cost": "The blended token price of a model, the provider's own listing.",
    "ghostship_ai_model_value": "The value of a model: the strength over the relative price.",
    "ghostship_ai_model_intelligence_index": "A benchmark index of a model.",
    "ghostship_ai_model_cost_per_task": "What a measured task costs, never a token price.",
    "ghostship_ai_model_throughput": "The median performance of a model.",
    "ghostship_ai_model_token_price": "A token price of a model, the provider's own listing.",
    "ghostship_ai_model_fact": "The state of the durable fact of a model.",
    "ghostship_ai_model_fact_fetched_timestamp_seconds": "When the fact of a model was read.",
    "ghostship_ai_model_fact_confidence": "The confidence a fact carries.",
    "ghostship_ai_model_winner": "One for the winner of a provider and tier.",
    "ghostship_ai_model_winner_position": "The position of the winner among the providers of a tier.",
    "ghostship_ai_policy_frontier_workhorse": (
        "One for every model the owner's policy names a frontier workhorse."
    ),
    "ghostship_ai_policy_excluded_model": (
        "One for every model the owner's policy excludes from selection; it "
        "stays visible in the usage and the quota readings."
    ),
    "ghostship_ai_model_new": (
        "One for a model the Artificial Analysis pull found that the last "
        "pull did not carry. It is the re-ranking trigger."
    ),
    "ghostship_ai_model_changed": (
        "One for a model whose Artificial Analysis measurement changed since "
        "the last pull."
    ),
    "ghostship_ai_feed_status": (
        "The state of the Artificial Analysis pull: the source, the state and "
        "the number of records."
    ),
    "ghostship_ai_model_aa_condition": (
        "The reasoning condition the benchmark measured the model under, and "
        "whether that condition is confirmed."
    ),
    "ghostship_ai_model_execution_reasoning": (
        "The execution reasoning the owner's policy proposes for a model: the "
        "default, the escalation, and whether the model supports them."
    ),
    "ghostship_ai_model_capacity_binding": (
        "The window that binds the capacity of a model, and the share of it "
        "that is left."
    ),
    "ghostship_ai_model_pace_binding": (
        "The window that binds the pace of a model, and the pace itself."
    ),
    "ghostship_ai_frontier_member": (
        "One for a model the owner's policy admits to the frontier, with the "
        "state it is in."
    ),
    "ghostship_ai_frontier_wait_seconds": (
        "The seconds until the frontier model becomes available again."
    ),
    "ghostship_ai_three_d_elo": "The measured AA-3D Elo of a model.",
    "ghostship_ai_model_value_3d": (
        "The value of a model for 3D work: the intelligence, the AA-3D "
        "capability and the cost, with the weights of the policy."
    ),
    "ghostship_ai_model_reserved": (
        "One for a model that is reserved for the 3D tier: it ranks after "
        "every other winner of the tier, and it is not used for the work of "
        "the tier while its provider's capacity is low."
    ),
    "ghostship_ai_calculation_component": "One for each part of the calculation of a winner.",
    "ghostship_ai_calculation_weight": "The weight of a part of the calculation.",
    "ghostship_ai_calculation_transform": (
        "The transform of a calculated input, with the name of the transform in "
        "force."
    ),
    "ghostship_ai_calculation_gate": "One for each gate of the tiers.",
    "ghostship_ai_quota_duration_seconds": "The length of a quota window.",
    "ghostship_ai_quota_expected_used_ratio": (
        "The usage an even spend would have reached by now; the white line."
    ),
    "ghostship_ai_quota_pace_delta_ratio": (
        "The expected usage minus the measured usage; positive is behind budget."
    ),
    "ghostship_ai_model_pace_delta_ratio": (
        "The most constraining pace among the windows of a model."
    ),
    "ghostship_ai_provider_paced_availability": (
        "The Paced Availability of a provider: the share left minus the "
        "expected share left in its most constraining window. Positive means "
        "the provider is ahead of the pace the window draws, and a higher "
        "number ranks first. It is the same number as the pace delta of that "
        "window."
    ),
    "ghostship_ai_model_paced_availability": (
        "The Paced Availability of a model: the share left minus the expected "
        "share left in its most constraining window. Positive means the model "
        "is ahead of the pace the window draws, and a higher number ranks "
        "first. It is the same number as the model's pace delta ratio."
    ),
    "ghostship_ai_provider_capacity_remaining_ratio": (
        "The lowest applicable account window of a provider; a spent window "
        "publishes zero, and an unknown window publishes nothing."
    ),
    "ghostship_ai_provider_capacity_windows": (
        "The account windows of a provider, split into known and unknown."
    ),
    "ghostship_ai_collection_timestamp_seconds": "When this collection ran.",
    "ghostship_ai_collection_duration_seconds": "How long this collection took.",
    "ghostship_ai_collection_duplicate_series": (
        "How many metric series this collection published twice. The repeats "
        "are dropped, so the file holds one series per name and label set."
    ),
}

GAUGE_METRICS = tuple(METRIC_HELP)


def log(message: str) -> None:
    print(f"ai-usage: {message}", file=sys.stderr, flush=True)


def resolve_t3_base_url(server_file: str) -> str:
    """Return a T3 base URL the host can reach."""
    raw = Path(server_file).read_text(encoding="utf-8").strip()
    base = ""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict):
        base = str(data.get("url") or data.get("server") or "").strip()
    elif isinstance(data, str):
        base = data.strip()
    else:
        # The bridge publishes a bare URL, not a JSON object.
        base = raw
    if not base:
        raise ValueError("no T3 server URL")
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(base)
    host = parts.hostname or ""
    if host and _resolves(host):
        return base
    address = _container_address(host)
    if not address:
        raise ValueError(f"cannot resolve the T3 container address for {host}")
    return urlunsplit((parts.scheme, f"{address}:{parts.port or 80}", parts.path, "", ""))


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
    except OSError:
        return False
    return True


# The Podman network the T3 Code container is attached to, and the resolver
# that serves its names. The address is looked up here instead of through
# the Podman API: the API is a root equivalent, and the collector has no
# reason to hold it.
PODMAN_NETWORK_FILE = "/etc/containers/networks/ghostship_net.json"
PODMAN_NETWORK = "ghostship_net"


def _container_address(container: str) -> str:
    """Return the address of a container on the Ghostship network.

    The published name of the container is resolved with the resolver of the
    Podman network it is attached to. The Podman API is not used: it is a
    root equivalent, and a name lookup does not need it.
    """
    resolver = _network_resolver()
    if not resolver:
        return ""
    return _resolve_name(container, resolver)


def _network_resolver(network_file: str = PODMAN_NETWORK_FILE) -> str:
    """The address of the resolver that serves the Podman network names."""
    try:
        document = json.loads(Path(network_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(document, dict):
        return ""
    for subnet in document.get("subnets") or []:
        if not isinstance(subnet, dict):
            continue
        gateway = subnet.get("gateway")
        if isinstance(gateway, str) and gateway:
            return gateway
    return ""


def _resolve_name(name: str, resolver: str, timeout: float = 5.0) -> str:
    """Resolve one name with the network resolver."""
    try:
        host = socket.gethostbyname_ex(name)
    except OSError:
        host = None
    if host and host[2]:
        return host[2][0]
    query = bytearray(b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00")
    for part in name.split("."):
        query += bytes([len(part)]) + part.encode("idna") if part.isascii() else bytes([0])
    query += b"\x00\x00\x01\x00\x01"
    try:
        connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        connection.settimeout(timeout)
        try:
            connection.sendto(bytes(query), (resolver, 53))
            answer, _address = connection.recvfrom(1024)
        finally:
            connection.close()
    except OSError:
        return ""
    if len(answer) < 16 or answer[3] & 0x0F:
        return ""
    count = int.from_bytes(answer[6:8], "big")
    offset = 12
    # The question: the name, then the type and the class.
    while offset < len(answer) and answer[offset]:
        offset += 1 + answer[offset]
    offset += 1 + 4
    for _ in range(count):
        if offset + 12 > len(answer):
            return ""
        if answer[offset] & 0xC0 == 0xC0:
            # A compressed name: the type and the class follow it.
            offset += 2
        else:
            while offset < len(answer) and answer[offset]:
                offset += 1 + answer[offset]
            offset += 1
        record_type = int.from_bytes(answer[offset : offset + 2], "big")
        record_length = int.from_bytes(answer[offset + 8 : offset + 10], "big")
        offset += 10
        if record_type == 1 and record_length == 4:
            return ".".join(str(byte) for byte in answer[offset : offset + 4])
        offset += record_length
    return ""


def read_session_token(path: str) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    token = data.get("token") if isinstance(data, dict) else None
    return token if isinstance(token, str) else ""


def collect_t3(now: float, catalog, context: dict[str, Any]) -> list[SourceResult]:
    """Read T3 Code's provider limits and usage history."""
    try:
        base_url = resolve_t3_base_url(T3_SERVER_FILE)
        token = read_session_token(T3_SESSION_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [
            SourceResult(
                source="t3",
                status="missing_credentials",
                reason=codes.UNAVAILABLE,
            )
        ]
    if not token:
        return [
            SourceResult(
                source="t3",
                status="missing_credentials",
                reason=codes.MISSING_CREDENTIALS,
            )
        ]
    try:
        with T3Client(base_url, token, timeout=180) as client:
            return t3source.collect(client, now, catalog=catalog, context=context)
    except (T3Error, OSError) as error:
        return [
            SourceResult(
                source="t3",
                status="error",
                reason=codes.RPC_FAILED,
            )
        ]


def free_model_samples(
    catalog: catalog_module.Catalog,
    offered: Iterable[tuple[str, str]],
    pool_models: Iterable[tuple[str, str]],
    now: float,
) -> list[Sample]:
    """List every model that can be used at no cost right now."""
    samples: list[Sample] = []
    offered_set = {(provider, model) for provider, model in offered}
    pool_set = {(provider, model) for provider, model in pool_models}
    seen: set[tuple[str, str, str]] = set()
    for provider in ("opencode-go", "opencode", "openrouter", "ollama"):
        for entry in catalog.free_models(provider):
            key = (entry["provider"], entry["model"], entry["tier"])
            if key in seen:
                continue
            seen.add(key)
            labels = {
                "provider": entry["provider"],
                "model": entry["model"],
                "tier": entry["tier"],
                "source": "model_catalog",
            }
            samples.append(("ghostship_ai_free_model", labels, 1.0))
            available = 1.0 if (entry["provider"], entry["model"]) in offered_set else 0.0
            samples.append(("ghostship_ai_free_model_available", labels, available))
            for kind, rate in entry["rates"].items():
                samples.append(
                    (
                        "ghostship_ai_free_model_price_usd_per_mtok",
                        {
                            "provider": entry["provider"],
                            "model": entry["model"],
                            "kind": kind,
                            "source": "model_catalog",
                        },
                        float(rate),
                    )
                )
            samples.append(
                (
                    "ghostship_ai_free_model_observed_timestamp_seconds",
                    labels,
                    now,
                )
            )
    for provider, model in sorted(pool_set):
        key = (provider, model, "free_pool")
        if key in seen:
            continue
        seen.add(key)
        labels = {
            "provider": provider,
            "model": model,
            "tier": "free_pool",
            "source": "free_pool",
        }
        samples.append(("ghostship_ai_free_model", labels, 1.0))
        samples.append(("ghostship_ai_free_model_available", labels, 1.0))
        samples.append(("ghostship_ai_free_model_observed_timestamp_seconds", labels, now))
    return samples


# The providers that report a window per model family. A window that names a
# family only applies to the models of that family; every other window
# applies to the whole account.
WINDOW_SCOPES = (
    ("3p-", ("claude", "gpt")),
    ("gemini-", ("gemini",)),
    ("fable", ("fable",)),
    ("sonnet", ("sonnet",)),
    ("opus", ("opus",)),
    ("haiku", ("haiku",)),
    ("sol", ("sol",)),
    ("astra", ("astra",)),
)


# A cooldown further out than this cannot be true. A millisecond timestamp
# read as seconds lands tens of thousands of years out, and a value like
# that is a broken reading, not a park. It is reported as an issue and it
# never blocks a route.
MAX_COOLDOWN_SECONDS = 366 * 24 * 3600.0

# The providers whose zero-price listing is a free route of its own. The
# OpenRouter free models and the Go subscription's free models cost nothing
# by construction, so they are dedicated free routes and they may hold the
# free tier.
FREE_ROUTE_PROVIDERS = ("opencode-go", "openrouter")

# The providers whose zero-price listing is a promotional route of a paid
# account. It costs nothing right now, it is not a free route of its own,
# and it competes in bulk. A model that is in both sets is a promotional
# route: the promotional zero price is checked first.
PROMO_PROVIDERS = ("opencode", "ollama")


def _window_scope(quota_id: str) -> tuple[str, ...]:
    """The model families a quota window applies to."""
    text = str(quota_id or "").lower()
    for marker, families in WINDOW_SCOPES:
        if marker in text:
            return families
    return ()


def _published_unlimited_routes(
    catalog: catalog_module.Catalog, inventory: Iterable[tuple[str, str]]
) -> list[tuple[str, str]]:
    """The routes the provider publishes as unlimited.

    The Go documentation lists its free routes as unlimited, and a live
    probe confirmed it: a free route answered while the paid monthly
    window of the plan was spent. The rule is the published one, and the
    catalog may not contradict it: a route the catalog prices is only
    unlimited when it prices it free.
    """
    free_prices = {
        str(entry.get("model") or "")
        for entry in (catalog.free_models(published_module.GO_PROVIDER) or [])
    }
    routes: list[tuple[str, str]] = []
    for provider, model in sorted(inventory or ()):
        if not published_module.unlimited_route(provider, model):
            continue
        entry = catalog.model_entry(provider, model)
        if entry is not None and model not in free_prices:
            # The catalog prices the route and it is not free: the published
            # unlimited listing does not apply to it.
            continue
        routes.append((str(provider), str(model)))
    return routes


def provider_limit_samples(
    inputs: Mapping[str, Any],
) -> list[Sample]:
    """The limits of every free provider, with the basis of each reading.

    A limit is published once per basis it was read with: the number the
    provider itself publishes, the ceiling the pool enforces, the number
    the provider's response headers carried, and the fact that a limit
    exists but no number is known for it. The bases are never mixed: a
    reader sees which reading a number came from.
    """
    samples: list[Sample] = []
    pool_providers = set(inputs.get("pool_providers") or ())
    limits = inputs.get("pool_limits") or {}
    for (provider, model, limit, scope), entry in sorted(limits.items()):
        value, basis = entry if isinstance(entry, tuple) else (entry, "configured")
        samples.append(
            (
                "ghostship_ai_provider_limit",
                {
                    "provider": provider,
                    "model": model,
                    "limit": limit,
                    "scope": scope,
                    "basis": basis,
                },
                float(value),
            )
        )
    for provider in sorted(pool_providers):
        for name, value, basis in pool_published.published_limits(provider):
            samples.append(
                (
                    "ghostship_ai_provider_limit",
                    {
                        "provider": provider,
                        "model": "*",
                        "limit": name,
                        "scope": "account",
                        "basis": basis,
                    },
                    float(value),
                )
            )
            samples.append(
                (
                    "ghostship_ai_pool_published_limit",
                    {
                        "provider": provider,
                        "limit": name,
                        "source": pool_published.PUBLISHED_SOURCE,
                        "checked_at": pool_published.PUBLISHED_CHECKED_AT,
                    },
                    float(value),
                )
            )
    return samples


def free_route_accounts(
    results: list[SourceResult],
    context: dict[str, Any],
    measured_windows: list[dict[str, Any]],
) -> set[str]:
    """The accounts that are observed to serve a free route on their own.

    The observation needs three facts at the same time: the paid allowance of
    the account is spent, the account is still ready, and it still offers a
    free model. A provider that is observed in that state is serving the
    free route independently of the paid allowance, so the paid allowance is
    not evidence about the free models of that account.

    It is an observation of the provider's behaviour, with a time, not a
    promise about the provider.
    """
    accounts: set[str] = set()
    ready = {
        str(instance)
        for instance, status in (context.get("instance_status") or {}).items()
        if str(status) == "ready"
    }
    # The instance that serves an account. The OpenCode instance serves
    # several accounts, and only the Go one has the paid allowance.
    instance_of = {
        "opencode-go": "opencode",
        "ollama": "opencode",
        "openrouter": "opencode",
    }
    spent: set[str] = set()
    for window in measured_windows:
        used = window.get("usedRatio")
        if not isinstance(used, (int, float)) or isinstance(used, bool):
            continue
        if float(used) >= 1.0 and str(window.get("kind")) in ("monthly", "weekly", "subscription"):
            spent.add(str(window.get("provider")))
    for account in spent:
        instance = instance_of.get(account, account)
        if instance in ready:
            accounts.add(account)
    return accounts


def ranking_inputs(
    results: list[SourceResult],
    catalog: catalog_module.Catalog,
    context: dict[str, Any],
    measured_windows: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Derive the ranking inputs from what the sources reported."""
    measured_windows = measured_windows or []
    moment = time.time() if now is None else float(now)
    inventory: set[tuple[str, str]] = set()
    for provider, model in context.get("offered_models") or []:
        inventory.add((str(provider), str(model)))
    free: set[tuple[str, str]] = set()
    promo: set[tuple[str, str]] = set()
    external: dict[tuple[str, str], bool] = {}
    usage: dict[tuple[str, str], float] = {}
    pool_providers: set[str] = set()
    pool_models: set[tuple[str, str]] = set()
    quota_used: dict[tuple[str, str, str, str], float] = {}
    quota_reset: dict[tuple[str, str, str, str], float] = {}
    for name, labels, value in _iter_samples(results):
        provider = labels.get("provider", "")
        model = labels.get("model", "")
        if name == "ghostship_ai_pool_model_info":
            inventory.add((provider, model))
            free.add((provider, model))
            pool_providers.add(provider)
            pool_models.add((provider, model))
        elif name == "ghostship_ai_pool_model_available":
            external[(provider, model)] = value > 0
        elif name == "ghostship_ai_free_model":
            # A free route of a free-route provider is a dedicated free
            # route; the zero-price listing of a paid account is a
            # promotional route that competes in bulk.
            if provider in PROMO_PROVIDERS:
                promo.add((provider, model))
            else:
                free.add((provider, model))
        elif name == "ghostship_ai_usage_tokens" and labels.get("window") == "7d":
            key = (provider, model)
            usage[key] = usage.get(key, 0.0) + value
        elif name == "ghostship_ai_quota_used_ratio" and model == "*":
            key = (
                provider,
                labels.get("account", "default"),
                labels.get("window", "other"),
                labels.get("quota", "default"),
                labels.get("source", ""),
            )
            quota_used[key] = value
        elif name == "ghostship_ai_quota_reset_timestamp_seconds" and model == "*":
            key = (
                provider,
                labels.get("account", "default"),
                labels.get("window", "other"),
                labels.get("quota", "default"),
                labels.get("source", ""),
            )
            quota_reset[key] = value
        elif name == "ghostship_ai_quota_used_ratio" and provider == "antigravity" and model != "*":
            # A model quota is more precise than the shared family window.
            key = (
                f"{provider}/{model}",
                labels.get("account", "default"),
                labels.get("window", "other"),
                labels.get("quota", "default"),
                labels.get("source", ""),
            )
            quota_used[key] = value
        elif name == "ghostship_ai_quota_reset_timestamp_seconds" and provider == "antigravity" and model != "*":
            key = (
                f"{provider}/{model}",
                labels.get("account", "default"),
                labels.get("window", "other"),
                labels.get("quota", "default"),
                labels.get("source", ""),
            )
            quota_reset[key] = value
    # The free routes of the T3 accounts, and the promotional zero-price
    # routes of the paid accounts. The two sets are kept apart: a model that
    # is in both is a promotional route, and the promotional zero price is
    # checked before the dedicated free class.
    for provider in FREE_ROUTE_PROVIDERS:
        for entry in catalog.free_models(provider):
            free.add((entry["provider"], entry["model"]))
    for provider in PROMO_PROVIDERS:
        for entry in catalog.free_models(provider):
            promo.add((entry["provider"], entry["model"]))
    windows: dict[str, list[Any]] = {}
    for measured in measured_windows:
        provider = str(measured.get("provider") or "")
        model = str(measured.get("model") or "*")
        used = measured.get("usedRatio")
        reset = measured.get("resetEpoch")
        duration = measured.get("durationSeconds")
        quota_id = str(measured.get("quotaId") or "default")
        # A window the source publishes but does not read is visible and it
        # does not constrain the route: an unknown reading is not evidence
        # that the account is exhausted. The provider stays visible, and the
        # lockout it reports is observed instead of inferred.
        gating = measured.get("gating")
        window = ranking_module.QuotaWindow(
            kind=str(measured.get("kind") or "other"),
            used_ratio=float(used) if isinstance(used, (int, float)) else None,
            reset_epoch=float(reset) if isinstance(reset, (int, float)) else None,
            applies_to=_window_scope(quota_id),
            quota_id=quota_id,
            duration_seconds=(
                float(duration) if isinstance(duration, (int, float)) and duration else None
            ),
            # When the provider last reported the window. A reading that is
            # old is not headroom.
            observed_at=(
                float(measured.get("observedAtEpoch"))
                if isinstance(measured.get("observedAtEpoch"), (int, float))
                else None
            ),
            basis=str(measured.get("basis") or ""),
            # When the entitlement of the window ends, when the provider
            # publishes an end. A promotion without a published end has no
            # end, and that is unknown rather than zero.
            ends_at=(
                float(measured.get("endsAt"))
                if isinstance(measured.get("endsAt"), (int, float))
                else None
            ),
            gating=gating is not False,
        )
        if model == "*":
            windows.setdefault(provider, []).append(window)
        else:
            # A window the provider reports for one model only.
            windows.setdefault(f"{provider}/{model}", []).append(window)
    # The routes the provider publishes as unlimited. The route carries a
    # window of its own, so it has a stated state instead of no state, and
    # the paid allowance of the account does not gate it. The documentation
    # lists those routes as unlimited "for a limited time", so the basis of
    # the window is a promotion and the end of it is unknown.
    for provider, model in _published_unlimited_routes(catalog, inventory):
        windows.setdefault(f"{provider}/{model}", []).append(
            ranking_module.QuotaWindow(
                kind="unlimited",
                used_ratio=0.0,
                reset_epoch=None,
                quota_id=published_module.UNLIMITED_QUOTA_ID,
                duration_seconds=None,
                ends_at=published_module.GO_FREE_ENDS_AT,
                observed_at=moment,
                basis=published_module.GO_FREE_BASIS,
            )
        )
    # The free pool's own evidence: the admissions of a route, its limits
    # and its cooldown. The admission is what lets a pool route hold the
    # free tier and take a workload.
    pool_admissions: dict[tuple[str, str, str], bool] = {}
    pool_limits: dict[tuple[str, str, str, str], float] = {}
    pool_cooldowns: dict[tuple[str, str], float] = {}
    for name, labels, value in _iter_samples(results):
        pool_provider = str(labels.get("provider") or "")
        pool_model = str(labels.get("model") or "")
        if name == "ghostship_ai_pool_model_admission":
            workload = str(labels.get("workload") or "")
            if workload:
                pool_admissions[(pool_provider, pool_model, workload)] = value > 0
        elif name == "ghostship_ai_pool_limit":
            key = (
                pool_provider,
                pool_model,
                str(labels.get("limit") or ""),
                str(labels.get("scope") or "account"),
            )
            pool_limits[key] = (float(value), "configured")
        elif name == "ghostship_ai_pool_observed_limit":
            # A limit the provider's own response headers carried.
            key = (
                pool_provider,
                pool_model,
                str(labels.get("limit") or ""),
                str(labels.get("scope") or "account"),
            )
            pool_limits.setdefault(key, (float(value), "observed"))
        elif name == "ghostship_ai_pool_model_cooldown_until_seconds":
            pool_cooldowns[(pool_provider, pool_model)] = float(value)
    # The cooldown is the pool's own evidence that a route is parked. A
    # cooldown that cannot be true is a broken reading, not a park: it is
    # reported as an issue and it never blocks a route.
    provider_cooldown = {
        provider: value
        for (provider, model), value in pool_cooldowns.items()
        if model == "*"
    }
    model_cooldown = {
        key: value
        for key, value in pool_cooldowns.items()
        if key[1] != "*"
    }
    pool_issues: dict[tuple[str, str], list[str]] = {}
    for (pool_provider, pool_model) in sorted(pool_models):
        cooldown = model_cooldown.get(
            (pool_provider, pool_model), provider_cooldown.get(pool_provider)
        )
        if cooldown is None:
            continue
        if cooldown > moment + MAX_COOLDOWN_SECONDS:
            pool_issues.setdefault((pool_provider, pool_model), []).append(
                "invalid_cooldown"
            )
            # The route is not blocked by a cooldown that cannot be true.
            external[(pool_provider, pool_model)] = True
        elif cooldown > moment:
            external[(pool_provider, pool_model)] = False
    pool_evidence: dict[tuple[str, str], dict[str, Any]] = {}
    for route in sorted(pool_models):
        pool_evidence.setdefault(
            route, {"admission": [], "limits": [], "issues": []}
        )
    for key, cooldown in sorted(pool_cooldowns.items()):
        pool_evidence.setdefault(
            (key[0], key[1]), {"admission": [], "limits": [], "issues": []}
        )
    for (pool_provider, pool_model, workload), admitted in sorted(pool_admissions.items()):
        entry = pool_evidence.setdefault(
            (pool_provider, pool_model), {"admission": [], "limits": [], "issues": []}
        )
        entry["admission"].append({"workload": workload, "admitted": admitted})
    for (pool_provider, pool_model, limit, scope), value in sorted(pool_limits.items()):
        entry = pool_evidence.setdefault(
            (pool_provider, pool_model), {"admission": [], "limits": [], "issues": []}
        )
        entry["limits"].append(
            {
                "limit": limit,
                "value": value[0],
                "scope": scope,
                "basis": value[1],
            }
        )
    for key, entry in pool_evidence.items():
        # A provider-wide cooldown belongs to every route of that provider.
        cooldown = pool_cooldowns.get(key)
        if cooldown is None:
            cooldown = provider_cooldown.get(key[0])
        entry["cooldown_until"] = cooldown
        entry["issues"] = list(pool_issues.get(key, []))
    return {
        "inventory": sorted(inventory),
        "free": free,
        "promo": promo,
        "external": external,
        "usage": usage,
        "windows": windows,
        "pool_providers": pool_providers,
        "pool_models": sorted(pool_models),
        "pool_evidence": pool_evidence,
        "pool_issues": pool_issues,
        "pool_limits": pool_limits,
    }


def ranking_samples(
    results: list[SourceResult],
    catalog: catalog_module.Catalog,
    context: dict[str, Any],
    now: float,
    *,
    t3_home: str = T3_HOME,
    state_path: str | None = None,
    aa_cache: dict[str, Any] | None = None,
    aa_3d_cache: dict[str, Any] | None = None,
    t3_state: str = T3_STATE_FILE,
) -> tuple[list[Sample], list[Any]]:
    """Rank every model we can use.

    Returns the ranking metrics and the ranked models themselves, so the
    snapshot can be built from the same ranking.
    """
    measured_windows: list[dict[str, Any]] = []
    for result in results:
        measured_windows.extend(result.windows)
    inputs = ranking_inputs(results, catalog, context, measured_windows, now=now)
    inventory = inputs["inventory"]
    free = inputs["free"]
    promo = inputs["promo"]
    external = inputs["external"]
    usage = inputs["usage"]
    windows = inputs["windows"]
    pool_providers = inputs["pool_providers"]
    context["free_models"] = free
    context["promo_models"] = promo
    context["pool_evidence"] = inputs["pool_evidence"]
    samples: list[Sample] = []
    # The limits of every free provider, with the basis of each reading.
    samples.extend(provider_limit_samples(inputs))
    # A cooldown that cannot be true is an issue, not a park. The route is
    # not blocked by it, and the issue is published so a reader sees it.
    for (provider, model), issues in sorted((inputs.get("pool_issues") or {}).items()):
        for issue in issues:
            samples.append(
                (
                    "ghostship_ai_pool_cooldown_invalid",
                    {"provider": provider, "model": model, "issue": issue},
                    1.0,
                )
            )
    three_d_scores: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        three_d = threed_module.collect(t3_home, catalog, inventory, now) or {}
    except (OSError, ValueError) as error:
        log(f"3D usage could not be read ({type(error).__name__})")
        three_d = {}
    for (provider, model), entry in three_d.items():
        if provider in pool_providers:
            # The 3D tier holds our frontier and bulk models; the free pool
            # belongs to the free tier.
            continue
        tokens = int(entry.get("tokens", 0))
        measured_3d = aa_3d.lookup(aa_3d_cache, provider, model)
        three_d_scores[(provider, model)] = {
            "usage_tokens": tokens,
            "elo": measured_3d.get("elo"),
            "source": measured_3d.get("source"),
            "observed_at": measured_3d.get("observed_at"),
            # A model belongs in the 3D tier only when the catalog proves it
            # can look at an image. The workload admission is verified at the
            # snapshot, where the durable evidence lives. A high token count
            # is not evidence of 3D work, and there is no 3D prior.
            "eligible": threed_module.visual_capable(
                catalog.model_entry(provider, model) if catalog is not None else None
            ),
        }
        samples.extend(
            threed_module.three_d_samples(provider, model, tokens=tokens, now=now)
        )
    rank_kwargs: dict[str, Any] = {
        "models": [
            ranking_module.ModelRecord(provider=provider, model=model)
            for provider, model in inventory
        ],
        "catalog": catalog,
        "quota_windows": windows,
        "free_models": free,
        "promo_models": promo,
        "external_availability": external,
        "usage_tokens": usage,
        "three_d_scores": three_d_scores,
        "aa_cache": aa_cache,
        "native_models": context.get("native_models") or {},
        "now": now,
        "state_path": state_path,
    }
    if "exclude_providers" in inspect.signature(ranking_module.rank_models).parameters:
        # The free inference pool belongs to the free tier, not to the bulk
        # tier of the paid accounts.
        rank_kwargs["exclude_providers"] = {"bulk": sorted(pool_providers)}
    if "promo_models" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["promo_models"] = sorted(promo)
    if "external_availability" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["external_availability"] = external
    if "free_route_accounts" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["free_route_accounts"] = sorted(
            free_route_accounts(results, context, measured_windows)
        )
    if "frontier_workhorses" in inspect.signature(ranking_module.rank_models).parameters:
        # The owner's list of frontier workhorses comes from the runtime
        # policy, so the producer and the reader share one list.
        rank_kwargs["frontier_workhorses"] = sorted(
            OWNER_POLICY.get("frontierPrimeModels") or ()
        )
    # The observed failures of the routes, read from the T3 Code state. A
    # route that is known to be broken does not win a tier, and it stays
    # visible with the reason and the moment it was observed.
    observed_failures = runtime_state_module.read_failures(t3_state, now)
    if "observed_failures" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["observed_failures"] = observed_failures
    for failure in observed_failures:
        samples.append(
            (
                "ghostship_ai_route_unavailable",
                {
                    "scope": str(failure.get("scope") or ""),
                    "target": str(failure.get("target") or ""),
                    "reason": str(failure.get("reason") or ""),
                },
                1.0,
            )
        )
        observed_at = failure.get("observed_at")
        if isinstance(observed_at, (int, float)) and not isinstance(observed_at, bool):
            samples.append(
                (
                    "ghostship_ai_route_unavailable_observed_timestamp_seconds",
                    {
                        "scope": str(failure.get("scope") or ""),
                        "target": str(failure.get("target") or ""),
                        "reason": str(failure.get("reason") or ""),
                    },
                    float(observed_at),
                )
            )
    context["observed_failures"] = observed_failures
    context["ranking_inventory"] = sorted(inventory)
    ranked = ranking_module.rank_models(**rank_kwargs)
    samples.extend(ranking_module.rank_samples(ranked, now=now))
    return samples, ranked


def read_facts(facts_path: str | None) -> dict[str, Any]:
    """The durable facts of the models, out of the facts file.

    The facts have their own file, so the ranking state and the facts never
    write over each other.
    """
    if not facts_path:
        return {}
    try:
        document = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict):
        return {}
    facts = document.get("facts")
    return facts if isinstance(facts, dict) else {}


def build_snapshot(
    results: list[SourceResult],
    ranked: list[Any],
    context: dict[str, Any],
    now: float,
    aa_cache: dict[str, Any] | None = None,
    measured_windows: list[dict[str, Any]] | None = None,
    catalog: Any = None,
    facts: dict[str, Any] | None = None,
    aa_3d_cache: dict[str, Any] | None = None,
    free_models: set[tuple[str, str]] | None = None,
    promo_models: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Build the canonical ranking and eligibility snapshot."""
    sources = []
    for result in results:
        observed = result.observed_at
        sources.append(
            {
                "id": result.source,
                "status": result.status,
                "reason": codes.reason(result.reason),
                "observed_at": (
                    None
                    if observed is None
                    else datetime.fromtimestamp(observed, tz=timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                ),
                "observed_at_epoch": observed,
                "last_success_at": (
                    datetime.fromtimestamp(now, tz=timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    if result.ok
                    else None
                ),
            }
        )
    snapshot = snapshot_module.build_snapshot(
        now=now,
        sources=sources,
        ranked=ranked,
        native_models=context.get("native_models") or {},
        policy=OWNER_POLICY,
        aa_cache=aa_cache,
        measured_windows=measured_windows,
        catalog=catalog,
        facts=facts,
        aa_3d_cache=aa_3d_cache,
        free_models=free_models or set(),
        promo_models=promo_models or set(),
        pool_evidence=context.get("pool_evidence") or {},
        inventory=context.get("ranking_inventory") or [],
    )
    if isinstance(snapshot, dict):
        quota_block = snapshot.setdefault("quota", {})
        if isinstance(quota_block, dict):
            quota_block["entitlements"] = quota_module.entitlements(
                measured_windows or [], now
            )
    return snapshot


def collect(
    now: float | None = None,
    *,
    t3_home: str = T3_HOME,
    secrets_env: str = SECRETS_ENV_FILE,
    pool_server: str = POOL_SERVER_FILE,
    pool_token: str = POOL_TOKEN_FILE,
    pool_ledger: str | None = POOL_LEDGER_FILE,
    catalog_path: str = CATALOG_FILE,
    state_path: str | None = None,
    window_state_path: str | None = providers_module.OLLAMA_WINDOW_STATE_FILE,
    t3_state: str = T3_STATE_FILE,
    aa_cache: dict[str, Any] | None = None,
    aa_3d_cache: dict[str, Any] | None = None,
) -> tuple[list[SourceResult], list[Sample], dict[str, Any]]:
    """Run every source and return the results, the extra samples, and the context."""
    moment = wall_clock() if now is None else now
    catalog = catalog_module.Catalog.load(catalog_path)
    context: dict[str, Any] = {}
    results: list[SourceResult] = []
    results.extend(collect_t3(moment, catalog, context))
    results.append(providers_module.read_grok(f"{t3_home}", moment))
    results.append(providers_module.read_opencode_go(f"{t3_home}", moment))
    results.append(providers_module.read_antigravity(f"{t3_home}", moment))
    # Our own requests of the last minute, counted from the T3 Code state.
    # A provider that publishes a per-minute limit and does not report it is
    # measured against this count, and the count is marked as such.
    request_counts = runtime_state_module.read_request_counts(t3_state, moment)
    results.append(
        providers_module.read_openrouter(
            secrets_env,
            moment,
            requests_last_minute=request_counts.get("openrouter"),
        )
    )
    results.append(
        providers_module.read_ollama(secrets_env, moment, state_path=window_state_path)
    )
    results.extend(pool_module.collect(pool_server, pool_token, pool_ledger, moment, home=t3_home))

    extra: list[Sample] = []
    ranked: list[Any] = []
    pool_models = {
        (labels.get("provider", ""), labels.get("model", ""))
        for name, labels, _value in _iter_samples(results)
        if name == "ghostship_ai_pool_model_info"
    }
    offered = context.get("offered_models") or []
    extra.extend(free_model_samples(catalog, offered, pool_models, moment))
    ranking_metrics, ranked = ranking_samples(
        results,
        catalog,
        context,
        moment,
        t3_home=t3_home,
        state_path=state_path,
        aa_cache=aa_cache,
        aa_3d_cache=aa_3d_cache,
    )
    extra.extend(ranking_metrics)
    context["ranked"] = ranked
    return results, extra, context


def _iter_samples(results: Iterable[SourceResult]):
    for result in results:
        yield from result.metrics


def feed_samples(snapshot: Mapping[str, Any]) -> list[Sample]:
    """The state of the Artificial Analysis pull, and what it found.

    The pull runs once a day, and a model that is new or whose measurement
    changed is the trigger for a re-ranking. The names are published so a
    reader can see which models the last pull brought in.
    """
    samples: list[Sample] = []
    quality = snapshot.get("quality_feed") or {}
    status = str(quality.get("status") or "missing")
    records = quality.get("records")
    samples.append(
        (
            "ghostship_ai_feed_status",
            {
                "source": "artificialanalysis",
                "status": status,
                "reason": str(quality.get("reason") or ""),
            },
            float(records) if isinstance(records, (int, float)) else 0.0,
        )
    )
    coverage = snapshot.get("aa_coverage") or {}
    states = coverage.get("states") or {}
    for state, count in sorted(states.items()):
        samples.append(
            (
                "ghostship_ai_feed_status",
                {
                    "source": "artificialanalysis",
                    "status": str(state),
                    "reason": "",
                },
                float(count) if isinstance(count, (int, float)) else 0.0,
            )
        )
    for entry in coverage.get("new_models") or ():
        if not isinstance(entry, Mapping):
            continue
        samples.append(
            (
                "ghostship_ai_model_new",
                {
                    "provider": str(entry.get("provider") or ""),
                    "model": str(entry.get("model") or ""),
                },
                1.0,
            )
        )
    for entry in coverage.get("changed_models") or ():
        if not isinstance(entry, Mapping):
            continue
        samples.append(
            (
                "ghostship_ai_model_changed",
                {
                    "provider": str(entry.get("provider") or ""),
                    "model": str(entry.get("model") or ""),
                },
                1.0,
            )
        )
    return samples


def decision_input_samples(
    snapshot: Mapping[str, Any],
) -> list[Sample]:
    """The inputs a decision was made on, as gauges.

    The benchmark condition and the execution reasoning are two different
    statements and both are published: the condition is what the benchmark
    measured, the reasoning is what the owner's policy proposes to run. The
    window that binds the capacity and the window that binds the pace are
    published apart, and the frontier membership carries its wait and its
    reset.
    """
    samples: list[Sample] = []
    for row in snapshot.get("candidates") or []:
        if not isinstance(row, Mapping):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not provider or not model:
            continue
        labels = {"provider": provider, "model": model}
        aa = row.get("aa") or {}
        condition = aa.get("condition") or {}
        measured_variant = str(condition.get("measured_variant") or "")
        if measured_variant:
            samples.append(
                (
                    "ghostship_ai_model_aa_condition",
                    {
                        **labels,
                        "variant": measured_variant,
                        "confirmed": (
                            "confirmed" if condition.get("confirmed") else "unconfirmed"
                        ),
                    },
                    1.0,
                )
            )
        execution = aa.get("execution") or {}
        default = str(execution.get("default") or "")
        escalation = str(execution.get("escalation") or "")
        if default or escalation:
            samples.append(
                (
                    "ghostship_ai_model_execution_reasoning",
                    {
                        **labels,
                        "default": default,
                        "escalation": escalation,
                        "supported": str(execution.get("state") or ""),
                    },
                    1.0,
                )
            )
        capacity = row.get("capacity") or {}
        capacity_binding = str(capacity.get("capacity_binding_id") or "")
        if capacity_binding:
            samples.append(
                (
                    "ghostship_ai_model_capacity_binding",
                    {**labels, "window": capacity_binding},
                    1.0,
                )
            )
        pace_binding = str(capacity.get("pace_binding_id") or "")
        if pace_binding:
            samples.append(
                (
                    "ghostship_ai_model_pace_binding",
                    {**labels, "window": pace_binding},
                    1.0,
                )
            )
        three_d = row.get("three_d") or {}
        elo = three_d.get("elo")
        if isinstance(elo, (int, float)) and not isinstance(elo, bool):
            samples.append(
                ("ghostship_ai_three_d_elo", labels, float(elo))
            )
        value_3d = (row.get("value_3d") or {}).get("value")
        if isinstance(value_3d, (int, float)) and not isinstance(value_3d, bool):
            samples.append(
                (
                    "ghostship_ai_model_value_3d",
                    {
                        **labels,
                        "cost_source": str(
                            (row.get("value_3d") or {}).get("cost_source") or ""
                        ),
                        "proxy": (
                            "proxy" if (row.get("value_3d") or {}).get("proxy") else "measured"
                        ),
                    },
                    float(value_3d),
                )
            )
        reserve = row.get("reserve") or {}
        if reserve.get("3d"):
            for tier in reserve.get("tiers") or ():
                samples.append(
                    (
                        "ghostship_ai_model_reserved",
                        {
                            **labels,
                            "tier": str(tier),
                            "reserve": "3d",
                            "withheld": (
                                "withheld" if reserve.get("withheld") else "ordered_last"
                            ),
                        },
                        1.0,
                    )
                )
    frontier = (snapshot.get("coverage") or {}).get("frontier") or {}
    for member in frontier.get("eligible") or ():
        if not isinstance(member, Mapping):
            continue
        labels = {
            "provider": str(member.get("provider") or ""),
            "model": str(member.get("model") or ""),
        }
        samples.append(
            (
                "ghostship_ai_frontier_member",
                {**labels, "state": str(member.get("state") or "")},
                1.0,
            )
        )
        wait = member.get("seconds_to_reset")
        if isinstance(wait, (int, float)) and not isinstance(wait, bool):
            samples.append(
                ("ghostship_ai_frontier_wait_seconds", labels, float(wait))
            )
    return samples


def render(
    results: list[SourceResult],
    extra: list[Sample],
    now: float,
    duration: float,
    snapshot: dict[str, Any] | None = None,
) -> str:
    writer = MetricWriter()
    for name, help_text in METRIC_HELP.items():
        writer.declare(name, "gauge", help_text)
    for result in results:
        provider = result.source
        writer.add(
            "ghostship_ai_source_success",
            {"source": result.source, "provider": provider},
            1.0 if result.ok else 0.0,
        )
        writer.add(
            "ghostship_ai_source_status",
            {
                "source": result.source,
                "provider": provider,
                "status": result.status,
                "reason": codes.reason(result.reason),
            },
            1.0,
        )
        if result.observed_at is not None:
            writer.add(
                "ghostship_ai_source_observed_timestamp_seconds",
                {"source": result.source, "provider": provider},
                result.observed_at,
            )
        writer.add(
            "ghostship_ai_source_duration_seconds",
            {"source": result.source, "provider": provider},
            result.duration_s,
        )
        if result.ok:
            writer.add(
                "ghostship_ai_source_last_success_timestamp_seconds",
                {"source": result.source, "provider": provider},
                now,
            )
    for provider, source in COVERAGE:
        writer.add(
            "ghostship_ai_provider_coverage",
            {"provider": provider, "source": source},
            1.0,
        )
    for result in results:
        for name, labels, value in result.metrics:
            writer.add(name, labels, value)
    for name, labels, value in extra:
        writer.add(name, labels, value)
    for name, labels, value in snapshot_module.decision_samples(snapshot or {}):
        writer.add(name, labels, value)
    for name, labels, value in snapshot_module.provider_capacity_samples(snapshot or {}):
        writer.add(name, labels, value)
    for name, labels, value in feed_samples(snapshot or {}):
        writer.add(name, labels, value)
    for name, labels, value in decision_input_samples(snapshot or {}):
        writer.add(name, labels, value)
    measured: list[dict[str, Any]] = []
    for result in results:
        measured.extend(result.windows)
    for name, labels, value in quota_module.quota_pace_samples(measured, now):
        writer.add(name, labels, value)
    for name, labels, value in quota_module.entitlement_samples(measured, now):
        writer.add(name, labels, value)
    for name, labels, value in quota_module.entitlement_display_samples(measured, now):
        writer.add(name, labels, value)
    writer.add("ghostship_ai_collection_timestamp_seconds", {}, now)
    writer.add("ghostship_ai_collection_duration_seconds", {}, duration)
    # A series is published once. A repeat is dropped and counted, and the
    # count is published, so a duplicate never passes unnoticed.
    if writer.duplicates:
        log(f"dropped {writer.duplicates} duplicate metric series")
    writer.add(
        "ghostship_ai_collection_duplicate_series", {}, float(writer.duplicates)
    )
    return writer.render()


def write_output(path: str, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect AI usage and limit metrics.")
    parser.add_argument(
        "--output",
        default="/var/lib/ghostship-container-metrics/ai-usage.prom",
        help="Where to write the Prometheus textfile.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print instead of writing a file.")
    parser.add_argument("--now", type=float, default=None, help="Override the current time.")
    parser.add_argument(
        "--state",
        default="/var/lib/ghostship-ai-usage/state.json",
        help="Where the model ranking keeps its evaluation state.",
    )
    parser.add_argument(
        "--window-state",
        default=providers_module.OLLAMA_WINDOW_STATE_FILE,
        help=(
            "Where the collector remembers the reset instants of the windows "
            "whose length it has to learn from them."
        ),
    )
    parser.add_argument(
        "--projection",
        action="append",
        default=[],
        help=(
            "An extra runtime presentation of the same snapshot bytes, for a "
            "consumer that reads a shared directory. Repeatable."
        ),
    )
    parser.add_argument(
        "--facts",
        default=FACTS_PATH,
        help="The durable facts of the models, written by the daily procedure.",
    )
    parser.add_argument(
        "--aa-catalog",
        default=CATALOG_FILE,
        help="The public model catalog, for the provider listed prices.",
    )
    parser.add_argument(
        "--aa-cache",
        default=AA_CACHE_PATH,
        help="The cached Artificial Analysis feed, written by the daily procedure.",
    )
    parser.add_argument(
        "--aa-3d-cache",
        default=AA_3D_CACHE_PATH,
        help=(
            "The bounded Artificial Analysis 3D snapshot (Elo, source, date and "
            "benchmark conditions), written by the pull of the public pages. "
            "Absent means no 3D rank."
        ),
    )
    parser.add_argument(
        "--snapshot",
        default=SNAPSHOT_PATH,
        help="Where the canonical ranking and eligibility snapshot is written.",
    )
    args = parser.parse_args(argv)

    started = time.monotonic()
    now = wall_clock() if args.now is None else args.now
    aa_cache = aa.load_cache(args.aa_cache, now)
    aa_3d_cache = aa_3d.load_cache(args.aa_3d_cache, now)
    results, extra, context = collect(
        now,
        state_path=args.state,
        window_state_path=args.window_state,
        aa_cache=aa_cache,
        aa_3d_cache=aa_3d_cache,
    )
    duration = time.monotonic() - started
    measured: list[dict[str, Any]] = []
    for result in results:
        measured.extend(result.windows)
    catalog = catalog_module.Catalog.load(args.aa_catalog)
    snapshot = build_snapshot(
        results,
        context.get("ranked") or [],
        context,
        now,
        aa_cache=aa_cache,
        measured_windows=measured,
        catalog=catalog,
        facts=read_facts(args.facts),
        free_models=context.get("free_models") or set(),
        promo_models=context.get("promo_models") or set(),
        aa_3d_cache=aa_3d_cache,
    )
    text = render(results, extra, now, duration, snapshot)
    if args.stdout:
        sys.stdout.write(text)
        sys.stdout.write(json.dumps(snapshot, indent=1, default=str) + "\n")
    else:
        write_output(args.output, text)
        log(f"wrote {len(text)} bytes to {args.output}")
    # The snapshot is the canonical answer for a consumer, so it is always
    # written, atomically, even in the dry run. A write that fails is an
    # error: the unit must fail visibly, never pass with a stale file.
    written = snapshot_module.write_snapshot(args.snapshot, snapshot)
    log(f"wrote {written} bytes to {args.snapshot}")
    for path, size in snapshot_module.publish(snapshot, args.projection):
        log(f"wrote {size} bytes to {path}")
    for result in results:
        log(f"{result.source}: {result.status} ({codes.reason(result.reason)})")
    log(f"wrote {len(text)} bytes to {'stdout' if args.stdout else args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
