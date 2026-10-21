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
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aa  # noqa: E402
import catalog as catalog_module  # noqa: E402
import codes  # noqa: E402
import pool as pool_module  # noqa: E402
import providers as providers_module  # noqa: E402
import ranking as ranking_module  # noqa: E402
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
CATALOG_FILE = f"{T3_HOME}/.cache/opencode/models.json"
# The smallest 3D prior that earns a place in the 3D tier.
THREE_D_MIN_PRIOR = 0.7

# The owner's direction for the agents that run in this environment. It is a
# policy, not a measurement, and it never changes a provider reading.
OWNER_POLICY = {
    "frontierPrimeModels": ("claude-opus-5-5", "gpt-6.1-sol"),
    "allowedGptModels": ("gpt-6.1-sol",),
    "backgroundProviderInstances": ("opencode",),
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
    "ghostship_ai_source_last_success_timestamp_seconds": "When a source last produced a reading.",
    "ghostship_ai_source_observed_timestamp_seconds": "When the reported reading was observed.",
    "ghostship_ai_source_duration_seconds": "How long a source took to read.",
    "ghostship_ai_quota_used_ratio": "Used share of a subscription or quota window.",
    "ghostship_ai_quota_reset_timestamp_seconds": "When a quota window resets.",
    "ghostship_ai_quota_observed_timestamp_seconds": "When a quota reading was observed.",
    "ghostship_ai_quota_state": "One for the state a provider reports for a window.",
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
    "ghostship_ai_model_rank": "The rank of a model inside a tier, 1 is best.",
    "ghostship_ai_model_score": "The ranking score of a model inside a tier.",
    "ghostship_ai_model_quality": "The quality score of a model.",
    "ghostship_ai_model_available": "Whether a model can be used right now.",
    "ghostship_ai_model_capacity_remaining": "The remaining share of a model's account capacity.",
    "ghostship_ai_model_capacity_expires_in_seconds": "When the model's account capacity expires.",
    "ghostship_ai_model_tier": "One for every tier a model belongs to.",
    "ghostship_ai_model_evaluated_timestamp_seconds": "When a model was last evaluated.",
    "ghostship_ai_three_d_prior": "How good a model is at 3D printing work.",
    "ghostship_ai_three_d_usage_tokens": "Tokens spent on 3D printing work.",
    "ghostship_ai_three_d_score": "The combined 3D score of a model.",
    "ghostship_ai_three_d_observed_timestamp_seconds": "When the 3D reading was taken.",
    "ghostship_ai_collection_timestamp_seconds": "When this collection ran.",
    "ghostship_ai_collection_duration_seconds": "How long this collection took.",
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


def _window_scope(quota_id: str) -> tuple[str, ...]:
    """The model families a quota window applies to."""
    text = str(quota_id or "").lower()
    for marker, families in WINDOW_SCOPES:
        if marker in text:
            return families
    return ()


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
) -> tuple[
    list[tuple[str, str]],
    set[tuple[str, str]],
    dict[tuple[str, str], float],
    dict[str, list[Any]],
    set[str],
]:
    """Derive the ranking inputs from what the sources reported."""
    measured_windows = measured_windows or []
    inventory: set[tuple[str, str]] = set()
    for provider, model in context.get("offered_models") or []:
        inventory.add((str(provider), str(model)))
    free: set[tuple[str, str]] = set()
    usage: dict[tuple[str, str], float] = {}
    pool_providers: set[str] = set()
    quota_used: dict[tuple[str, str, str, str], float] = {}
    quota_reset: dict[tuple[str, str, str, str], float] = {}
    for name, labels, value in _iter_samples(results):
        provider = labels.get("provider", "")
        model = labels.get("model", "")
        if name == "ghostship_ai_pool_model_info":
            inventory.add((provider, model))
            free.add((provider, model))
            pool_providers.add(provider)
        elif name == "ghostship_ai_free_model":
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
    for provider in ("opencode-go", "opencode", "openrouter", "ollama"):
        for entry in catalog.free_models(provider):
            free.add((entry["provider"], entry["model"]))
    windows: dict[str, list[Any]] = {}
    for measured in measured_windows:
        provider = str(measured.get("provider") or "")
        model = str(measured.get("model") or "*")
        used = measured.get("usedRatio")
        reset = measured.get("resetEpoch")
        duration = measured.get("durationSeconds")
        quota_id = str(measured.get("quotaId") or "default")
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
        )
        if model == "*":
            windows.setdefault(provider, []).append(window)
        else:
            # A window the provider reports for one model only.
            windows.setdefault(f"{provider}/{model}", []).append(window)
    return sorted(inventory), free, usage, windows, pool_providers


def ranking_samples(
    results: list[SourceResult],
    catalog: catalog_module.Catalog,
    context: dict[str, Any],
    now: float,
    *,
    t3_home: str = T3_HOME,
    state_path: str | None = None,
) -> tuple[list[Sample], list[Any]]:
    """Rank every model we can use.

    Returns the ranking metrics and the ranked models themselves, so the
    snapshot can be built from the same ranking.
    """
    measured_windows: list[dict[str, Any]] = []
    for result in results:
        measured_windows.extend(result.windows)
    inventory, free, usage, windows, pool_providers = ranking_inputs(
        results, catalog, context, measured_windows
    )
    samples: list[Sample] = []
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
        prior = float(entry.get("prior", 0.0))
        tokens = int(entry.get("tokens", 0))
        score = float(entry.get("score", 0.0))
        three_d_scores[(provider, model)] = {
            "score": score,
            "prior": prior,
            "usage_tokens": tokens,
            # Only a model that is genuinely good at 3D work belongs in the
            # tier; the tier stays small and useful.
            "eligible": prior >= THREE_D_MIN_PRIOR,
        }
        samples.extend(
            threed_module.three_d_samples(provider, model, prior=prior, tokens=tokens, now=now)
        )
    rank_kwargs: dict[str, Any] = {
        "models": [
            ranking_module.ModelRecord(provider=provider, model=model)
            for provider, model in inventory
        ],
        "catalog": catalog,
        "quota_windows": windows,
        "free_models": free,
        "usage_tokens": usage,
        "three_d_scores": three_d_scores,
        "now": now,
        "state_path": state_path,
    }
    if "exclude_providers" in inspect.signature(ranking_module.rank_models).parameters:
        # The free inference pool belongs to the free tier, not to the bulk
        # tier of the paid accounts.
        rank_kwargs["exclude_providers"] = {"bulk": sorted(pool_providers)}
    if "free_route_accounts" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["free_route_accounts"] = sorted(
            free_route_accounts(results, context, measured_windows)
        )
    ranked = ranking_module.rank_models(**rank_kwargs)
    samples.extend(ranking_module.rank_samples(ranked, now=now))
    return samples, ranked


def build_snapshot(
    results: list[SourceResult],
    ranked: list[Any],
    context: dict[str, Any],
    now: float,
    aa_cache: dict[str, Any] | None = None,
    measured_windows: list[dict[str, Any]] | None = None,
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
    return snapshot_module.build_snapshot(
        now=now,
        sources=sources,
        ranked=ranked,
        native_models=context.get("native_models") or {},
        policy=OWNER_POLICY,
        aa_cache=aa_cache,
        measured_windows=measured_windows,
    )


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
    results.append(providers_module.read_openrouter(secrets_env, moment))
    results.append(providers_module.read_ollama(secrets_env, moment))
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
    )
    extra.extend(ranking_metrics)
    context["ranked"] = ranked
    return results, extra, context


def _iter_samples(results: Iterable[SourceResult]):
    for result in results:
        yield from result.metrics


def render(results: list[SourceResult], extra: list[Sample], now: float, duration: float) -> str:
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
    writer.add("ghostship_ai_collection_timestamp_seconds", {}, now)
    writer.add("ghostship_ai_collection_duration_seconds", {}, duration)
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
        "--aa-cache",
        default=AA_CACHE_PATH,
        help="The cached Artificial Analysis feed, written by the daily procedure.",
    )
    parser.add_argument(
        "--snapshot",
        default=SNAPSHOT_PATH,
        help="Where the canonical ranking and eligibility snapshot is written.",
    )
    args = parser.parse_args(argv)

    started = time.monotonic()
    now = wall_clock() if args.now is None else args.now
    results, extra, context = collect(now, state_path=args.state)
    aa_cache = aa.load_cache(args.aa_cache, now)
    duration = time.monotonic() - started
    text = render(results, extra, now, duration)
    measured: list[dict[str, Any]] = []
    for result in results:
        measured.extend(result.windows)
    snapshot = build_snapshot(
        results,
        context.get("ranked") or [],
        context,
        now,
        aa_cache=aa_cache,
        measured_windows=measured,
    )
    if args.stdout:
        sys.stdout.write(text)
        sys.stdout.write(json.dumps(snapshot, indent=1, default=str) + "\n")
    else:
        write_output(args.output, text)
    # The snapshot is the canonical answer for a consumer, so it is always
    # written, atomically, even in the dry run.
    snapshot_module.write_snapshot(args.snapshot, snapshot)
    for result in results:
        log(f"{result.source}: {result.status} ({codes.reason(result.reason)})")
    log(f"wrote {len(text)} bytes to {'stdout' if args.stdout else args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
