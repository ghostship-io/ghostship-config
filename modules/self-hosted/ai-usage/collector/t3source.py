"""T3 Code as a collection source.

Two readings come from T3 Code itself:

* the provider statuses, which carry the subscription windows T3 knows about
  (Codex, Claude, Grok, OpenCode Go, Antigravity);
* the usage summary, which aggregates the local provider session history into
  token and cost buckets.

Both are read-only RPC calls. Nothing here changes T3 Code behaviour, and no
provider limit is invented when T3 does not report one.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

import codes
from metrics import SourceResult, Sample
from t3client import T3Client, T3Error
from util import iso_to_epoch

try:  # pragma: no cover - zoneinfo is present on NixOS
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

DEFAULT_TIMEZONE = "Pacific/Honolulu"
USAGE_DAYS = 30

# T3 provider instance ids mapped onto the provider names used everywhere in
# this collector.
INSTANCE_PROVIDERS = {
    "codex": "codex",
    "claudeAgent": "claude",
    "grok": "grok",
    "antigravity": "antigravity",
    "cursor": "cursor",
    "pi": "pi",
    "opencode": "opencode-go",
    "muse": "muse",
}

# The OpenCode instance reports the Go subscription windows.
WINDOW_PROVIDERS = {"go_rolling": "opencode-go", "go_weekly": "opencode-go", "go_monthly": "opencode-go"}

# The Ollama Cloud account has its own session window and its own weekly
# window. The OpenCode instance serves it beside the Go subscription, so a
# window that names Ollama belongs to the Ollama account and not to the Go
# one. A window that names no account at all stays with its instance.
OLLAMA_WINDOW_MARKERS = ("ollama",)

# Model ids carried by the OpenCode instance name their upstream provider.
MODEL_PREFIX_PROVIDERS = {
    "opencode-go": "opencode-go",
    "opencode": "opencode",
    "ollama-cloud": "ollama",
    "ollama": "ollama",
    "openrouter": "openrouter",
}


def _zone(name: str):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _day_bounds(epoch: float, zone) -> str:
    return datetime.fromtimestamp(epoch, tz=zone).strftime("%Y-%m-%d")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def split_model(provider: str, model: str) -> tuple[str, str]:
    """Split an OpenCode style model id into provider and model."""
    if provider == "opencode" and "/" in model:
        prefix, _, rest = model.partition("/")
        mapped = MODEL_PREFIX_PROVIDERS.get(prefix)
        if mapped:
            return mapped, rest
    return provider, model


def _bucket_samples(buckets: Iterable[dict[str, Any]], window: str) -> list[Sample]:
    """Turn T3 usage buckets into token, cost, and record samples."""
    tokens: dict[tuple[str, str], dict[str, float]] = {}
    costs: dict[tuple[str, str, str], float] = {}
    unpriced: dict[tuple[str, str], float] = {}
    for bucket in buckets:
        provider, model = split_model(str(bucket.get("provider")), str(bucket.get("model")))
        totals = bucket.get("totals") or {}
        key = (provider, model)
        entry = tokens.setdefault(
            key,
            {"input": 0.0, "cache_read": 0.0, "cache_write": 0.0, "output": 0.0, "reasoning": 0.0},
        )
        entry["input"] += float(totals.get("uncachedInputTokens") or 0)
        entry["cache_read"] += float(totals.get("cachedInputTokens") or 0)
        entry["cache_write"] += float(totals.get("cacheCreationTokens") or 0)
        entry["output"] += float(totals.get("outputTokens") or 0)
        entry["reasoning"] += float(totals.get("reasoningTokens") or 0)
        cost = bucket.get("costUsd")
        source = str(bucket.get("costSource") or "unpriced")
        if cost is not None and source != "unpriced":
            basis = "provider_reported" if source == "providerReported" else "api_equivalent"
            costs[(provider, model, basis)] = costs.get((provider, model, basis), 0.0) + float(cost)
        else:
            unpriced[key] = unpriced.get(key, 0.0) + float(bucket.get("unpricedRecords") or 0)

    samples: list[Sample] = []
    for (provider, model), entry in sorted(tokens.items()):
        for kind, value in entry.items():
            if value <= 0:
                continue
            samples.append(
                (
                    "ghostship_ai_usage_tokens",
                    {
                        "provider": provider,
                        "model": model,
                        "kind": kind,
                        "window": window,
                        "source": "t3_history",
                        "basis": "api_equivalent",
                    },
                    value,
                )
            )
    for (provider, model, basis), value in sorted(costs.items()):
        if value <= 0:
            continue
        samples.append(
            (
                "ghostship_ai_usage_cost_usd",
                {
                    "provider": provider,
                    "model": model,
                    "window": window,
                    "source": "t3_history",
                    "basis": basis,
                },
                value,
            )
        )
    for (provider, model), value in sorted(unpriced.items()):
        if value <= 0:
            continue
        samples.append(
            (
                "ghostship_ai_usage_unpriced_records",
                {"provider": provider, "model": model, "window": window, "source": "t3_history"},
                value,
            )
        )
    return samples


def read_usage(client: T3Client, now: float, timezone_name: str = DEFAULT_TIMEZONE) -> dict[str, Any]:
    """Read the daily and hourly usage summaries from T3 Code."""
    zone = _zone(timezone_name)
    today = _day_bounds(now, zone)
    since_day = (
        datetime.fromtimestamp(now, tz=zone) - timedelta(days=USAGE_DAYS - 1)
    ).strftime("%Y-%m-%d")
    daily = client.call(
        "server.getUsageSummary",
        {
            "sinceDay": since_day,
            "untilDay": today,
            "timeZone": timezone_name,
            "resolution": "day",
        },
    )
    hourly = client.call(
        "server.getUsageSummary",
        {
            "sinceDay": _day_bounds(now - 86400, timezone.utc),
            "untilDay": _day_bounds(now, timezone.utc),
            "timeZone": timezone_name,
            "resolution": "hour",
            "sinceTime": _iso(now - 86400),
            "untilTime": _iso(now),
        },
    )
    return {"daily": daily or {}, "hourly": hourly or {}}


def _window_buckets(
    buckets: Iterable[dict[str, Any]], since_day: str, until_day: str, key: str = "day"
) -> list[dict[str, Any]]:
    return [
        bucket
        for bucket in buckets
        if since_day <= str(bucket.get(key) or "") <= until_day
    ]


def collect(
    client: T3Client,
    now: float,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    catalog=None,
    context: dict[str, Any] | None = None,
) -> list[SourceResult]:
    """Collect T3 provider limits and usage history."""
    results: list[SourceResult] = []
    results.append(_collect_limits(client, context))
    results.append(_collect_usage(client, now, timezone_name=timezone_name, catalog=catalog))
    return results


def _model_options(model: dict[str, Any]) -> list[dict[str, Any]]:
    """The options a model offers, with the value that is selected.

    Only the option name and its current value are kept: no prompt, no
    diagnostic, and nothing that identifies a person.
    """
    capabilities = model.get("capabilities")
    if not isinstance(capabilities, dict):
        return []
    descriptors = capabilities.get("optionDescriptors")
    if not isinstance(descriptors, list):
        return []
    options: list[dict[str, Any]] = []
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        identifier = descriptor.get("id")
        if not isinstance(identifier, str) or not identifier:
            continue
        value = descriptor.get("currentValue")
        # A descriptor without a current value is still the option's published
        # descriptor: the model offers it, the run setting is simply not
        # reported.
        option: dict[str, Any] = {"id": identifier}
        if descriptor.get("type") in ("boolean", "select"):
            option["type"] = descriptor["type"]
        if isinstance(value, (str, bool, int, float)):
            option["currentValue"] = value
        for key in ("values", "allowed", "allowedValues", "choices", "enum"):
            allowed = descriptor.get(key)
            if isinstance(allowed, (list, tuple)) and 0 < len(allowed) <= 64:
                cleaned = [
                    item
                    for item in allowed
                    if isinstance(item, (str, int, float, bool))
                ]
                if cleaned:
                    option["values"] = cleaned
                    break
        # The stock shape lists the allowed choices as objects:
        # options=[{id, label, ...}]. The id is the value.
        choices = descriptor.get("options")
        if "values" not in option and isinstance(choices, list) and 0 < len(choices) <= 64:
            cleaned = [
                str(entry.get("id"))
                for entry in choices
                if isinstance(entry, Mapping)
                and isinstance(entry.get("id"), str)
                and entry.get("id")
            ]
            if cleaned:
                option["values"] = cleaned
        options.append(option)
    return options


def _model_label(model: dict[str, Any]) -> str:
    """The label the instance gives one model, or an empty string.

    The label is a name, never an id: the model id is published beside it.
    """
    for field in ("name", "label", "displayName", "display_name", "title"):
        value = model.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _collect_limits(client: T3Client, context: dict[str, Any] | None = None) -> SourceResult:
    started = time.monotonic()
    providers: list[dict[str, Any]] = []
    status = "ok"
    try:
        refreshed = client.call("server.refreshProviders", {})
        providers = list((refreshed or {}).get("providers") or [])
    except T3Error:
        # The cached provider status is still worth reporting.
        status = "partial"
        try:
            config = client.call("server.getConfig", {}) or {}
            providers = list(config.get("providers") or [])
        except T3Error:
            return SourceResult(
                source="t3",
                status="error",
                reason=codes.RPC_FAILED,
                duration_s=time.monotonic() - started,
            )
    samples: list[Sample] = []
    windows: list[dict[str, Any]] = []
    reason_code = codes.OK
    observed: float | None = None
    offered: list[tuple[str, str]] = []
    native: dict[tuple[str, str], dict[str, Any]] = {}
    provider_states: dict[str, str] = {}
    for provider in providers:
        instance = str(provider.get("instanceId") or "")
        name = INSTANCE_PROVIDERS.get(instance, instance)
        for model in provider.get("models") or []:
            if not isinstance(model, dict):
                continue
            slug = model.get("slug")
            if not isinstance(slug, str) or not slug:
                continue
            if instance == "opencode":
                pair = split_model("opencode", slug)
            else:
                pair = (name, slug)
            offered.append(pair)
            native[pair] = {
                "providerInstance": instance,
                "available": provider.get("enabled") is not False and provider.get("status") == "ready",
                "modelId": slug,
                # The label the instance gives the model, when it gives one.
                # It is the name T3 Code's model catalog carries for it.
                "name": _model_label(model),
                "options": _model_options(model),
            }
        state = str(provider.get("status") or "")
        provider_states[name] = state
        limits = provider.get("usageLimits")
        if state == "ready" and isinstance(limits, dict):
            unavailable = limits.get("unavailable")
            if isinstance(unavailable, dict) and unavailable.get("reason"):
                # The stock shape: the provider is ready, but its limits probe
                # reported that it could not read them. The source read part
                # of the picture, so it is partial, and the reason is a code.
                status = "partial"
                reason_code = (
                    codes.UNSUPPORTED
                    if str(unavailable.get("reason")) == "unsupported"
                    else codes.PROBE_FAILED
                )
        if not isinstance(limits, dict):
            continue
        checked_at = iso_to_epoch(limits.get("checkedAt"))
        if checked_at:
            observed = max(observed or 0.0, checked_at)
        for window in limits.get("windows") or []:
            window_id = str(window.get("id") or "")
            provider_name = WINDOW_PROVIDERS.get(window_id, name)
            if window_id not in WINDOW_PROVIDERS:
                # A window that names its own account belongs to that
                # account, not to the instance that reported it. The Ollama
                # Cloud session and weekly windows are reported by the
                # OpenCode instance, and they are the Ollama account's.
                lowered = window_id.lower()
                if any(marker in lowered for marker in OLLAMA_WINDOW_MARKERS):
                    provider_name = "ollama"
            used = window.get("usedPercent")
            if used is None:
                continue
            labels = {
                "provider": provider_name,
                "account": "default",
                "model": "*",
                "window": str(window.get("kind") or "other"),
                "quota": window_id or "default",
                "source": "t3",
            }
            samples.append(("ghostship_ai_quota_used_ratio", labels, _clamp(float(used) / 100.0)))
            reset = iso_to_epoch(window.get("resetsAt"))
            if reset is not None:
                samples.append(("ghostship_ai_quota_reset_timestamp_seconds", labels, reset))
            if checked_at is not None:
                samples.append(("ghostship_ai_quota_observed_timestamp_seconds", labels, checked_at))
            minutes = window.get("windowDurationMins")
            duration = float(minutes) * 60.0 if isinstance(minutes, (int, float)) else None
            windows.append(
                {
                    "provider": provider_name,
                    "account": "default",
                    "model": "*",
                    "kind": str(window.get("kind") or "other"),
                    "quotaId": window_id or "default",
                    "usedRatio": float(used) / 100.0,
                    "resetEpoch": reset,
                    "durationSeconds": duration,
                    "source": "t3",
                    "observedAtEpoch": checked_at,
                }
            )
    for provider, state in sorted(provider_states.items()):
        samples.append(
            (
                "ghostship_ai_provider_status",
                {"provider": provider, "state": state or "unknown"},
                1.0,
            )
        )
    if context is not None:
        context["offered_models"] = offered
        context["native_models"] = native
        context["instance_status"] = {
            str(provider.get("instanceId") or ""): str(provider.get("status") or "")
            for provider in providers
        }
        context["provider_states"] = provider_states
    return SourceResult(
        source="t3",
        status=status,
        reason=reason_code if status == "ok" else (
            reason_code if reason_code != codes.OK else codes.RPC_FAILED
        ),
        metrics=samples,
        observed_at=observed,
        duration_s=time.monotonic() - started,
        windows=windows,
    )


def _collect_usage(
    client: T3Client,
    now: float,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    catalog=None,
) -> SourceResult:
    started = time.monotonic()
    try:
        summary = read_usage(client, now, timezone_name)
    except T3Error as error:
        return SourceResult(
            source="t3_usage",
            status="error",
            reason=codes.RPC_FAILED,
            duration_s=time.monotonic() - started,
        )
    zone = _zone(timezone_name)
    today = _day_bounds(now, zone)
    daily_buckets = list((summary["daily"] or {}).get("buckets") or [])
    hourly_buckets = list((summary["hourly"] or {}).get("buckets") or [])
    samples: list[Sample] = []

    for window, since_day in (("7d", _day_bounds(now - 6 * 86400, zone)), ("30d", _day_bounds(now - 29 * 86400, zone))):
        selected = _window_buckets(daily_buckets, since_day, today)
        samples.extend(_bucket_samples(selected, window))

    if hourly_buckets:
        samples.extend(_bucket_samples(hourly_buckets, "24h"))

    # A model T3 could not price is still worth a dollar estimate when the
    # public model catalog knows its rate.
    if catalog is not None:
        samples.extend(_catalog_costs(catalog, samples, "7d"))
        samples.extend(_catalog_costs(catalog, samples, "30d"))
        samples.extend(_catalog_costs(catalog, samples, "24h"))

    observed = iso_to_epoch((summary["daily"] or {}).get("readAt"))
    return SourceResult(
        source="t3_usage",
        status="ok",
        reason=codes.OK,
        metrics=samples,
        observed_at=observed,
        duration_s=time.monotonic() - started,
    )


def _catalog_costs(catalog, samples: list[Sample], window: str) -> list[Sample]:
    """Price the models T3 left unpriced with the public model catalog."""
    unpriced = {
        (labels.get("provider"), labels.get("model"))
        for name, labels, _value in samples
        if name == "ghostship_ai_usage_unpriced_records" and labels.get("window") == window
    }
    if not unpriced:
        return []
    priced = {key for key in unpriced if catalog.price_for(key[0], key[1]) is not None}
    if not priced:
        return []
    totals: dict[tuple[str, str], dict[str, float]] = {}
    for name, labels, value in samples:
        if name != "ghostship_ai_usage_tokens" or labels.get("window") != window:
            continue
        key = (labels.get("provider", ""), labels.get("model", ""))
        if key not in priced:
            continue
        entry = totals.setdefault(key, {})
        entry[labels.get("kind", "input")] = entry.get(labels.get("kind", "input"), 0.0) + value
    result: list[Sample] = []
    for (provider, model), kinds in sorted(totals.items()):
        price = catalog.price_for(provider, model)
        if price is None:
            continue
        cost = 0.0
        for kind, tokens in kinds.items():
            rate = price.get(kind)
            if rate is None:
                rate = price.get("input" if kind == "cache_read" else kind, 0.0)
            cost += tokens * float(rate) / 1_000_000.0
        result.append(
            (
                "ghostship_ai_usage_cost_usd",
                {
                    "provider": provider,
                    "model": model,
                    "window": window,
                    "source": "t3_history",
                    "basis": "api_equivalent",
                },
                cost,
            )
        )
    return result
