"""Direct readers for the providers T3 Code cannot fully report.

T3 Code knows about its own provider sessions, but the subscription windows of
several accounts live behind provider APIs that T3 does not read, and two
accounts have no T3 reader at all. This module reads them directly so the
dashboard covers every account in use:

* Grok: the CLI chat proxy's credit billing.
* OpenCode Go: the Zen usage endpoint, read with the credential OpenCode
  itself holds, so the reading survives a token rotation.
* Antigravity: Google's quota endpoints, for both the shared family windows
  and the per-model quotas (Gemini included) that T3 merges away.
* OpenRouter: credits, key usage, and the free-model request allowance.
* Ollama: the Ollama Cloud usage and balance endpoints.

Every reader is read-only: it never dispatches inference, rotates a
credential, or changes an account.
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import codes
from metrics import SourceResult, Sample
from util import HttpResult, http_request, iso_to_epoch, read_env_file

HttpCall = Callable[..., HttpResult]

GROK_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
OPENCODE_GO_USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
OLLAMA_USAGE_URL = "https://ollama.com/api/usage"
OLLAMA_BALANCE_URL = "https://ollama.com/api/balance"
ANTIGRAVITY_ENDPOINTS = (
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
)
ANTIGRAVITY_USER_AGENT = (
    "antigravity/hub/1.0.0 (aidev_client; os_type=linux; arch=arm64; cl=963137146)"
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


# The basis of a window: where its number comes from. A number the provider
# reported itself, a number its documentation publishes, and a published
# limit counted against our own requests are never mixed.
BASIS_PROVIDER = "provider_reported"
BASIS_PROVIDER_DERIVED = "provider_reported+derived_length"
BASIS_PUBLISHED = "published"
BASIS_PUBLISHED_COUNTED = "published+counted"


def _next_utc_midnight(now: float) -> float:
    """The next midnight UTC, as epoch seconds."""
    from datetime import datetime, timedelta, timezone

    moment = datetime.fromtimestamp(float(now), tz=timezone.utc)
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight + timedelta(days=1)).timestamp()


def _load_window_state(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    """Read the remembered window observations, tolerating a missing file."""
    if not path:
        return {}
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _save_window_state(path: str | os.PathLike[str] | None, state: Mapping[str, Any]) -> None:
    """Remember the window observations for the next collection."""
    if not path:
        return
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(
            json.dumps(dict(state), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, target)
    except OSError:
        pass


def _quota_sample(
    name: str,
    provider: str,
    account: str,
    model: str,
    window: str,
    source: str,
    value: float,
) -> Sample:
    return (
        name,
        {
            "provider": provider,
            "account": account,
            "model": model,
            "window": window,
            "source": source,
        },
        value,
    )


def _account_sample(
    provider: str,
    account: str,
    kind: str,
    unit: str,
    window: str,
    source: str,
    value: float,
) -> Sample:
    return (
        "ghostship_ai_account_amount",
        {
            "provider": provider,
            "account": account,
            "kind": kind,
            "unit": unit,
            "window": window,
            "source": source,
        },
        value,
    )


# ---------------------------------------------------------------- Grok
def read_grok(home: str | os.PathLike[str], now: float, http: HttpCall = http_request) -> SourceResult:
    started = time.monotonic()
    source = "grok"
    auth_path = Path(home) / ".grok" / "auth.json"
    token = ""
    try:
        credentials = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        credentials = {}
    if isinstance(credentials, dict):
        for key, value in credentials.items():
            if not isinstance(value, dict):
                continue
            if "auth.x.ai" not in str(key) and "accounts.x.ai" not in str(key):
                continue
            if value.get("auth_mode") == "api_key":
                continue
            candidate = value.get("key")
            if isinstance(candidate, str) and candidate.strip():
                token = candidate.strip()
                break
    if not token:
        return SourceResult(
            source=source,
            status="missing_credentials",
            reason=codes.MISSING_CREDENTIALS,
            duration_s=time.monotonic() - started,
        )
    response = http(GROK_BILLING_URL, headers={"Authorization": f"Bearer {token}"})
    if not response.ok:
        return SourceResult(
            source=source,
            status="error",
            reason=codes.http_reason(response.status),
            duration_s=time.monotonic() - started,
        )
    body = response.json() or {}
    config = body.get("config") if isinstance(body, dict) else None
    config = config if isinstance(config, dict) else {}
    period = config.get("currentPeriod") if isinstance(config.get("currentPeriod"), dict) else {}
    period_type = str(period.get("type") or "").replace("USAGE_PERIOD_TYPE_", "").lower()
    window = {"weekly": "weekly", "monthly": "monthly"}.get(period_type, "subscription")
    percent = config.get("creditUsagePercent")
    samples: list[Sample] = []
    if isinstance(percent, (int, float)):
        used = _clamp(float(percent) / 100.0)
    elif period.get("start") and period.get("end"):
        # Grok omits a zero percentage while keeping the billing period.
        used = 0.0
    else:
        return SourceResult(
            source=source,
            status="partial",
            reason=codes.INVALID_RESPONSE,
            duration_s=time.monotonic() - started,
        )
    labels = {
        "provider": "grok",
        "account": "default",
        "model": "*",
        "window": window,
        "quota": "subscription",
        "source": source,
    }
    samples.append(("ghostship_ai_quota_used_ratio", labels, used))
    reset = iso_to_epoch(period.get("end"))
    if reset is not None:
        samples.append(("ghostship_ai_quota_reset_timestamp_seconds", labels, reset))
    samples.append(("ghostship_ai_quota_observed_timestamp_seconds", labels, now))
    start = iso_to_epoch(period.get("start"))
    duration = None
    if start is not None and reset is not None and reset > start:
        duration = reset - start
    windows = [
        {
            "provider": "grok",
            "account": "default",
            "model": "*",
            "kind": window,
            "quotaId": "subscription",
            "usedRatio": used,
            "resetEpoch": reset,
            "durationSeconds": duration,
            "source": source,
            "observedAtEpoch": now,
        }
    ]
    return SourceResult(
        source=source,
        status="ok",
        reason=codes.OK,
        metrics=samples,
        observed_at=now,
        duration_s=time.monotonic() - started,
        windows=windows,
    )


# --------------------------------------------------------- OpenCode Go
def read_opencode_go(
    home: str | os.PathLike[str], now: float, http: HttpCall = http_request
) -> SourceResult:
    started = time.monotonic()
    source = "opencode-go"
    token = _opencode_go_token(Path(home))
    if not token:
        return SourceResult(
            source=source,
            status="missing_credentials",
            reason=codes.MISSING_CREDENTIALS,
            duration_s=time.monotonic() - started,
        )
    response = http(
        OPENCODE_GO_USAGE_URL,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "opencode/2.0.0"},
    )
    if not response.ok:
        return SourceResult(
            source=source,
            status="error",
            reason=codes.http_reason(response.status),
            duration_s=time.monotonic() - started,
        )
    body = response.json() or {}
    usage = body.get("usage") if isinstance(body, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    if not usage:
        return SourceResult(
            source=source,
            status="partial",
            reason=codes.INVALID_RESPONSE,
            duration_s=time.monotonic() - started,
        )
    windows_by_key = {"rolling": "session", "weekly": "weekly", "monthly": "monthly"}
    windows = windows_by_key
    samples: list[Sample] = []
    for key, window in windows.items():
        entry = usage.get(key)
        if not isinstance(entry, dict):
            continue
        percent = entry.get("percent")
        if not isinstance(percent, (int, float)):
            continue
        labels = {
            "provider": "opencode-go",
            "account": "default",
            "model": "*",
            "window": window,
            "quota": key,
            "source": source,
        }
        samples.append(("ghostship_ai_quota_used_ratio", labels, _clamp(float(percent) / 100.0)))
        reset = iso_to_epoch(entry.get("resetsAt"))
        if reset is not None:
            samples.append(("ghostship_ai_quota_reset_timestamp_seconds", labels, reset))
        samples.append(("ghostship_ai_quota_observed_timestamp_seconds", labels, now))
        state = entry.get("status")
        if isinstance(state, str) and state:
            samples.append(
                (
                    "ghostship_ai_quota_state",
                    {
                        "provider": "opencode-go",
                        "account": "default",
                        "model": "*",
                        "window": window,
                        "quota": key,
                        "source": source,
                        "state": state,
                    },
                    1.0,
                )
            )
    windows = []
    for key, duration in (("rolling", 5 * 3600.0), ("weekly", 7 * 86400.0), ("monthly", 30 * 86400.0)):
        entry = usage.get(key)
        if not isinstance(entry, dict):
            continue
        percent = entry.get("percent")
        if not isinstance(percent, (int, float)):
            continue
        windows.append(
            {
                "provider": "opencode-go",
                "account": "default",
                "model": "*",
                "kind": windows_by_key[key],
                "quotaId": key,
                "usedRatio": _clamp(float(percent) / 100.0),
                "resetEpoch": iso_to_epoch(entry.get("resetsAt")),
                "durationSeconds": duration,
                "source": source,
                "observedAtEpoch": now,
            }
        )
    return SourceResult(
        source=source,
        status="ok",
        reason=codes.OK,
        metrics=samples,
        observed_at=now,
        duration_s=time.monotonic() - started,
        windows=windows,
    )


def _opencode_go_token(home: Path) -> str:
    """Find the OpenCode Console credential without touching the account."""
    database = home / ".local" / "share" / "opencode" / "opencode.db"
    if database.exists():
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5)
            try:
                row = connection.execute(
                    "SELECT value FROM credential WHERE integration_id = 'opencode' "
                    "AND active IS NOT 0 ORDER BY active DESC, time_created DESC, id DESC LIMIT 1"
                ).fetchone()
            finally:
                connection.close()
        except sqlite3.Error:
            row = None
        if row and isinstance(row[0], str):
            try:
                stored = json.loads(row[0])
            except ValueError:
                stored = {}
            if isinstance(stored, dict):
                for key in ("key", "access"):
                    value = stored.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    auth_path = home / ".local" / "share" / "opencode" / "auth.json"
    try:
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        auth = {}
    entry = auth.get("opencode-go") if isinstance(auth, dict) else None
    if isinstance(entry, dict) and entry.get("type") == "api":
        value = entry.get("key")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# ----------------------------------------------------------- Antigravity
def read_antigravity(
    home: str | os.PathLike[str], now: float, http: HttpCall = http_request
) -> SourceResult:
    started = time.monotonic()
    source = "antigravity"
    pattern = str(Path(home) / ".t3" / "userdata" / "providers" / "antigravity" / "*" / "antigravity-acp" / "acp_token.json")
    matches = sorted(glob.glob(pattern))
    if not matches:
        return SourceResult(
            source=source,
            status="missing_credentials",
            reason=codes.MISSING_CREDENTIALS,
            duration_s=time.monotonic() - started,
        )
    try:
        token = json.loads(Path(matches[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        token = {}
    if not isinstance(token, dict) or not token.get("refresh_token"):
        return SourceResult(
            source=source,
            status="missing_credentials",
            reason=codes.MISSING_CREDENTIALS,
            duration_s=time.monotonic() - started,
        )
    access = _antigravity_access_token(token, http)
    if not access:
        return SourceResult(
            source=source,
            status="error",
            reason=codes.PROBE_FAILED,
            duration_s=time.monotonic() - started,
        )
    payload = json.dumps({"project": token["project_id"]} if token.get("project_id") else {}).encode()
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json",
        "User-Agent": ANTIGRAVITY_USER_AGENT,
    }
    buckets: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    failures = 0
    for endpoint in ANTIGRAVITY_ENDPOINTS:
        for operation, handler in (
            ("retrieveUserQuotaSummary", "summary"),
            ("fetchAvailableModels", "models"),
        ):
            response = http(
                f"{endpoint}/v1internal:{operation}",
                method="POST",
                headers=headers,
                body=payload,
                timeout=30,
            )
            if not response.ok:
                failures += 1
                continue
            body = response.json() or {}
            if handler == "summary":
                _merge_summary(buckets, body)
            else:
                _merge_models(models, body)
    if not buckets and not models:
        return SourceResult(
            source=source,
            status="error",
            reason=codes.PROBE_FAILED,
            duration_s=time.monotonic() - started,
        )
    samples: list[Sample] = []
    windows: list[dict[str, Any]] = []
    for bucket_id, bucket in sorted(buckets.items()):
        fraction = bucket.get("remainingFraction")
        if not isinstance(fraction, (int, float)):
            continue
        window = "weekly" if bucket.get("window") == "weekly" else "session"
        if bucket.get("window") not in ("weekly", "5h"):
            window = "shared"
        labels = {
            "provider": "antigravity",
            "account": "default",
            "model": "*",
            "window": window,
            "quota": bucket_id,
            "source": source,
        }
        samples.append(("ghostship_ai_quota_used_ratio", labels, _clamp(1.0 - float(fraction))))
        reset = iso_to_epoch(bucket.get("resetTime"))
        if reset is not None:
            samples.append(("ghostship_ai_quota_reset_timestamp_seconds", labels, reset))
        samples.append(("ghostship_ai_quota_observed_timestamp_seconds", labels, now))
        duration = None
        if bucket.get("window") == "5h":
            duration = 5 * 3600.0
        elif bucket.get("window") == "weekly":
            duration = 7 * 86400.0
        windows.append(
            {
                "provider": "antigravity",
                "account": "default",
                "model": "*",
                "kind": window,
                "quotaId": bucket_id,
                "usedRatio": _clamp(1.0 - float(fraction)),
                "resetEpoch": reset,
                "durationSeconds": duration,
                "source": source,
                "observedAtEpoch": now,
            }
        )
    for model_id, entry in sorted(models.items()):
        for key, window in (("quotaInfo", "quota"), ("weeklyQuotaInfo", "weekly")):
            quota = entry.get(key)
            if not isinstance(quota, dict):
                continue
            fraction = quota.get("remainingFraction")
            if not isinstance(fraction, (int, float)):
                continue
            labels = {
                "provider": "antigravity",
                "account": "default",
                "model": model_id,
                "window": window,
                "quota": key,
                "source": source,
            }
            samples.append(("ghostship_ai_quota_used_ratio", labels, _clamp(1.0 - float(fraction))))
            reset = iso_to_epoch(quota.get("resetTime"))
            if reset is not None:
                samples.append(("ghostship_ai_quota_reset_timestamp_seconds", labels, reset))
            samples.append(("ghostship_ai_quota_observed_timestamp_seconds", labels, now))
            windows.append(
                {
                    "provider": "antigravity",
                    "account": "default",
                    "model": model_id,
                    "kind": window,
                    "quotaId": key,
                    "usedRatio": _clamp(1.0 - float(fraction)),
                    "resetEpoch": reset,
                    "durationSeconds": None,
                    "source": source,
                    "observedAtEpoch": now,
                }
            )
    status = "ok" if not failures else "partial"
    return SourceResult(
        source=source,
        status=status,
        reason=codes.OK if not failures else codes.PROBE_FAILED,
        metrics=samples,
        observed_at=now,
        duration_s=time.monotonic() - started,
        windows=windows,
    )


def _antigravity_access_token(token: dict[str, Any], http: HttpCall) -> str:
    body = (
        f"client_id={token.get('client_id', '')}&client_secret={token.get('client_secret', '')}"
        f"&refresh_token={token.get('refresh_token', '')}&grant_type=refresh_token"
    ).encode()
    response = http(
        "https://oauth2.googleapis.com/token",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
    )
    if not response.ok:
        return ""
    payload = response.json() or {}
    access = payload.get("access_token") if isinstance(payload, dict) else None
    return access if isinstance(access, str) else ""


def _merge_summary(buckets: dict[str, dict[str, Any]], body: Any) -> None:
    if not isinstance(body, dict):
        return
    groups = body.get("groups")
    if not isinstance(groups, list) or not any(
        isinstance(group, dict) and group.get("buckets") for group in groups
    ):
        groups = [{"buckets": body.get("buckets")}]
    for group in groups:
        for bucket in (group or {}).get("buckets") or []:
            if not isinstance(bucket, dict):
                continue
            bucket_id = str(bucket.get("bucketId") or "")
            if not bucket_id or bucket.get("disabled"):
                continue
            previous = buckets.get(bucket_id)
            if previous is None:
                buckets[bucket_id] = bucket
                continue
            old = previous.get("remainingFraction")
            new = bucket.get("remainingFraction")
            if isinstance(old, (int, float)) and isinstance(new, (int, float)) and new < old:
                buckets[bucket_id] = bucket


def _merge_models(models: dict[str, dict[str, Any]], body: Any) -> None:
    if not isinstance(body, dict):
        return
    entries = body.get("models")
    if not isinstance(entries, dict):
        return
    for model_id, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        previous = models.get(model_id)
        if previous is None:
            models[model_id] = entry
            continue
        for key in ("quotaInfo", "weeklyQuotaInfo"):
            old = previous.get(key)
            new = entry.get(key)
            if not isinstance(new, dict):
                continue
            if not isinstance(old, dict):
                previous[key] = new
                continue
            old_fraction = old.get("remainingFraction")
            new_fraction = new.get("remainingFraction")
            if isinstance(old_fraction, (int, float)) and isinstance(new_fraction, (int, float)):
                if new_fraction < old_fraction:
                    previous[key] = new


# ----------------------------------------------------------- OpenRouter
# The published per-minute allowance of the OpenRouter free models. The
# documentation states it; the provider does not report it on the key
# endpoint, and it only appears on the headers of a refused request. The
# number is a published limit, and our own requests are counted against it.
OPENROUTER_FREE_REQUESTS_PER_MINUTE = 20
OPENROUTER_MINUTE_SECONDS = 60.0
OPENROUTER_DAILY_SECONDS = 86400.0


def read_openrouter(
    env_path: str | os.PathLike[str],
    now: float,
    http: HttpCall = http_request,
    requests_last_minute: int | None = None,
) -> SourceResult:
    """Read the OpenRouter account: its credits, its key usage, and its windows.

    The free models of the account share one allowance: the number of free
    model requests the key may make in the current UTC day. The key endpoint
    reports how many of them are left, and the day ends at midnight UTC.
    The per-minute limit is published rather than reported, so it is counted
    against our own requests and it is marked as such.
    """
    started = time.monotonic()
    source = "openrouter"
    key = read_env_file(env_path).get("OPENROUTER_API_KEY", "")
    if not key:
        return SourceResult(
            source=source,
            status="missing_credentials",
            reason=codes.MISSING_CREDENTIALS,
            duration_s=time.monotonic() - started,
        )
    headers = {"Authorization": f"Bearer {key}"}
    credits = http(OPENROUTER_CREDITS_URL, headers=headers)
    account = http(OPENROUTER_KEY_URL, headers=headers)
    if not (credits.ok or account.ok):
        return SourceResult(
            source=source,
            status="error",
            reason=codes.http_reason(credits.status or account.status),
            duration_s=time.monotonic() - started,
        )
    samples: list[Sample] = []
    windows: list[dict[str, Any]] = []
    credit_body = (credits.json() or {}).get("data") if credits.ok else None
    if isinstance(credit_body, dict):
        total = credit_body.get("total_credits")
        used = credit_body.get("total_usage")
        if isinstance(total, (int, float)):
            samples.append(
                _account_sample("openrouter", "default", "balance", "usd", "total", source, float(total))
            )
        if isinstance(used, (int, float)):
            # The lifetime usage of the account, which is not the same figure
            # as the usage of the last thirty days.
            samples.append(
                _account_sample("openrouter", "default", "usage", "usd", "total", source, float(used))
            )
    key_body = (account.json() or {}).get("data") if account.ok else None
    if isinstance(key_body, dict):
        for window, field in (("24h", "usage_daily"), ("7d", "usage_weekly"), ("30d", "usage_monthly")):
            value = key_body.get(field)
            if isinstance(value, (int, float)):
                samples.append(
                    _account_sample("openrouter", "default", "usage", "usd", window, source, float(value))
                )
        limit = key_body.get("limit")
        if isinstance(limit, (int, float)):
            samples.append(
                _account_sample("openrouter", "default", "cap", "usd", "30d", source, float(limit))
            )
        samples.append(
            (
                "ghostship_ai_account_flag",
                {
                    "provider": "openrouter",
                    "account": "default",
                    "flag": "free_tier",
                    "source": source,
                },
                1.0 if key_body.get("is_free_tier") else 0.0,
            )
        )
        free = key_body.get("free_model_daily_requests")
        if isinstance(free, dict):
            for kind, field in (("used", "used"), ("limit", "limit"), ("remaining", "remaining")):
                value = free.get(field)
                if isinstance(value, (int, float)):
                    samples.append(
                        _account_sample(
                            "openrouter",
                            "default",
                            f"free_models_{kind}",
                            "requests",
                            "24h",
                            source,
                            float(value),
                        )
                    )
            daily = _openrouter_daily_window(free, now)
            if daily is not None:
                windows.append(daily)
                samples.extend(_window_samples(daily))
    minute = _openrouter_minute_window(now, requests_last_minute)
    if minute is not None:
        windows.append(minute)
        samples.extend(_window_samples(minute))
    for sample in list(samples):
        if sample[0] == "ghostship_ai_account_amount":
            samples.append(
                (
                    "ghostship_ai_account_observed_timestamp_seconds",
                    sample[1],
                    now,
                )
            )
    return SourceResult(
        source=source,
        status="ok" if credits.ok and account.ok else "partial",
        reason=codes.OK if credits.ok and account.ok else codes.HTTP_ERROR,
        metrics=samples,
        observed_at=now,
        duration_s=time.monotonic() - started,
        windows=windows,
    )


def _window_samples(window: Mapping[str, Any]) -> list[Sample]:
    """The quota samples of one measured window."""
    labels = {
        "provider": window["provider"],
        "account": window["account"],
        "model": window["model"],
        "window": window["kind"],
        "quota": window["quotaId"],
        "source": window["source"],
    }
    samples: list[Sample] = [
        ("ghostship_ai_quota_used_ratio", dict(labels), float(window["usedRatio"]))
    ]
    if window.get("resetEpoch") is not None:
        samples.append(
            ("ghostship_ai_quota_reset_timestamp_seconds", dict(labels), float(window["resetEpoch"]))
        )
    samples.append(
        ("ghostship_ai_quota_observed_timestamp_seconds", dict(labels), float(window["observedAtEpoch"]))
    )
    samples.append(("ghostship_ai_quota_state", {**labels, "state": "measured"}, 1.0))
    return samples


def _openrouter_daily_window(
    free: Mapping[str, Any], now: float
) -> dict[str, Any] | None:
    """The daily allowance of the free models, as a window.

    The counter of the provider counts every free model request of the day,
    and the limit is the allowance of the tier, so the share of the window
    that is left is the remaining share of the limit. A counter above the
    limit means the allowance is spent.
    """
    limit = free.get("limit")
    remaining = free.get("remaining")
    used = free.get("used")
    if not isinstance(limit, (int, float)) or isinstance(limit, bool) or float(limit) <= 0.0:
        return None
    if not isinstance(remaining, (int, float)) or isinstance(remaining, bool):
        return None
    share = 1.0 - float(remaining) / float(limit)
    if isinstance(used, (int, float)) and not isinstance(used, bool) and float(used) > float(limit):
        # The counter is above the allowance: the day is spent.
        share = 1.0
    return {
        "provider": "openrouter",
        "account": "default",
        "model": "*",
        "kind": "daily",
        "quotaId": "free-models-per-day",
        "usedRatio": _clamp(share),
        # The counter covers the current UTC day, so the day ends at the next
        # midnight UTC.
        "resetEpoch": _next_utc_midnight(now),
        "durationSeconds": OPENROUTER_DAILY_SECONDS,
        "source": "openrouter",
        "observedAtEpoch": now,
        "basis": BASIS_PROVIDER,
    }


def _openrouter_minute_window(
    now: float, requests_last_minute: int | None
) -> dict[str, Any] | None:
    """The published per-minute allowance of the free models.

    The provider does not report this limit on the key endpoint, so the
    number is the published one and the usage is our own count of the
    requests we made in the last minute. It is a published limit counted
    against our own requests, never a reading of the provider.
    """
    if requests_last_minute is None:
        return None
    counted = max(0, int(requests_last_minute))
    share = counted / float(OPENROUTER_FREE_REQUESTS_PER_MINUTE)
    return {
        "provider": "openrouter",
        "account": "default",
        "model": "*",
        "kind": "minute",
        "quotaId": "free-models-per-minute",
        "usedRatio": _clamp(share),
        "resetEpoch": float(now) + OPENROUTER_MINUTE_SECONDS,
        "durationSeconds": OPENROUTER_MINUTE_SECONDS,
        "source": "openrouter",
        "observedAtEpoch": now,
        "basis": BASIS_PUBLISHED_COUNTED,
    }


# --------------------------------------------------------------- Ollama
# The Ollama Cloud account has a session window and a weekly window. The
# session window is the one a lockout names: the provider refuses the
# account with "you have reached your session usage limit".
OLLAMA_WINDOWS = ("session", "weekly")

# The length of the weekly window. The weekly allowance resets on Monday at
# 00:00 UTC, so the window is a week long.
OLLAMA_WEEKLY_SECONDS = 7 * 86400.0

# The length of the session window while its cadence is unknown. The
# provider publishes no length for it, so this is a derived fallback and it
# is marked as derived: the real length is learned from the step between two
# successive resets.
OLLAMA_SESSION_SECONDS = 86400.0

# The bounds a learned session length has to sit in. A step that is not a
# plausible window length is not a length.
OLLAMA_MIN_WINDOW_SECONDS = 60.0
OLLAMA_MAX_WINDOW_SECONDS = 90 * 86400.0

# The file that remembers the reset instants of the Ollama windows, so the
# length of a session window can be learned from the step between two
# successive resets. It holds those instants and nothing else.
OLLAMA_WINDOW_STATE_FILE = "/var/lib/ghostship-ai-usage/ollama-windows.json"

# The fields the usage endpoint may publish for a window. The endpoint is
# the provider's own, and its shape is not ours to invent: a field that is
# not there is an unknown window, never a zero.
_OLLAMA_LIMIT_FIELDS = {
    "session": ("session", "session_limit", "sessionUsage", "session_usage"),
    "weekly": ("weekly", "weekly_limit", "weeklyUsage", "weekly_usage"),
}
_OLLAMA_USED_FIELDS = ("used", "used_ratio", "usedPercent", "percent", "consumed")
_OLLAMA_LIMIT_TOTAL_FIELDS = ("limit", "total", "max", "quota")
_OLLAMA_RESET_FIELDS = ("reset_at", "resetsAt", "reset", "expires_at", "resets_at")


def _ollama_window_reading(
    body: Any, window: str
) -> tuple[float | None, float | None, float | None]:
    """The used share, the limit and the reset of one Ollama window.

    The reading is the provider's own. A window the endpoint does not
    describe has no reading: the share is unknown, and an unknown share is
    never published as zero.
    """
    if not isinstance(body, Mapping):
        return None, None, None
    entry = None
    for field in _OLLAMA_LIMIT_FIELDS[window]:
        candidate = body.get(field)
        if isinstance(candidate, Mapping):
            entry = candidate
            break
    if entry is None:
        return None, None, None
    used: float | None = None
    used_is_share = False
    for field in _OLLAMA_USED_FIELDS:
        value = entry.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            used = float(value)
            # A share is already a share; an amount is not.
            used_is_share = field in ("used_ratio",)
            break
    limit: float | None = None
    for field in _OLLAMA_LIMIT_TOTAL_FIELDS:
        value = entry.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            limit = float(value)
            break
    reset: float | None = None
    for field in _OLLAMA_RESET_FIELDS:
        value = entry.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            reset = float(value)
            break
        if isinstance(value, str) and value:
            reset = iso_to_epoch(value)
            if reset is not None:
                break
    if used is not None and not used_is_share:
        if limit is not None and limit > 0:
            # The amount that was used, over the amount the window allows.
            used = used / limit
        elif used > 1.0:
            # A percentage of the window.
            used = used / 100.0
    return used, limit, reset


def read_ollama(
    env_path: str | os.PathLike[str],
    now: float,
    http: HttpCall = http_request,
    state_path: str | os.PathLike[str] | None = None,
) -> SourceResult:
    """Read the Ollama Cloud account: its request counters and its windows.

    The account has a session window and a weekly window, and the balance
    endpoint is what reports them: the share of the window that is left and
    the instant it resets. The length of the weekly window is a week. The
    provider publishes no length for the session window, so it is learned
    from the step between two successive resets, and it is marked as derived
    until it is known.
    """
    started = time.monotonic()
    source = "ollama"
    key = read_env_file(env_path).get("OLLAMA_API_KEY", "")
    if not key:
        return SourceResult(
            source=source,
            status="missing_credentials",
            reason=codes.MISSING_CREDENTIALS,
            duration_s=time.monotonic() - started,
        )
    headers = {"Authorization": f"Bearer {key}"}
    samples: list[Sample] = []
    windows: list[dict] = []
    failures = 0
    usage_body: Any = {}
    for window, range_value in (("24h", "24h"), ("7d", "7d"), ("30d", "30d")):
        response = http(f"{OLLAMA_USAGE_URL}?range={range_value}", headers=headers)
        if not response.ok:
            failures += 1
            continue
        body = response.json() or {}
        usage_body = body
        totals = body.get("totals") if isinstance(body, dict) else None
        totals = totals if isinstance(totals, dict) else {}
        requests = totals.get("request_count")
        if isinstance(requests, (int, float)):
            samples.append(
                _account_sample("ollama", "default", "requests", "requests", window, source, float(requests))
            )
            samples.append(
                (
                    "ghostship_ai_account_observed_timestamp_seconds",
                    {
                        "provider": "ollama",
                        "account": "default",
                        "kind": "requests",
                        "unit": "requests",
                        "window": window,
                        "source": source,
                    },
                    now,
                )
            )
    # The session and the weekly window of the account. The balance
    # endpoint is what reports them: the share of the window that is left
    # and the instant it resets. A window the endpoint does not describe is
    # published as unknown: the provider stays visible, and the lockout it
    # reports is what makes the route unavailable.
    previous = _load_window_state(state_path)
    balance = http(OLLAMA_BALANCE_URL, headers=headers)
    measured: dict[str, dict[str, Any]] = {}
    if balance.ok:
        measured = {
            reading["kind"]: reading
            for reading in _ollama_balance_windows(balance.json() or {}, now, previous)
        }
    else:
        failures += 1
    for window in OLLAMA_WINDOWS:
        labels = {
            "provider": "ollama",
            "account": "default",
            "model": "*",
            "window": window,
            "quota": window,
            "source": source,
        }
        reading = measured.get(window)
        if reading is None:
            # The balance endpoint did not describe the window. The legacy
            # reading of the usage endpoint is tried once, and a window that
            # still has no number stays unknown.
            used, _limit, reset = _ollama_window_reading(usage_body, window)
            if used is None:
                # The window exists, its number is unknown. It is published as
                # an unknown state and it does not gate the route: an unknown
                # reading is not evidence that the account is exhausted.
                samples.append(
                    ("ghostship_ai_quota_state", {**labels, "state": "unknown"}, 1.0)
                )
                windows.append(
                    {
                        "provider": "ollama",
                        "account": "default",
                        "model": "*",
                        "kind": window,
                        "quotaId": window,
                        "usedRatio": None,
                        "resetEpoch": reset,
                        "durationSeconds": None,
                        "source": source,
                        "observedAtEpoch": now,
                        # The window does not constrain the route on its own: the
                        # account's lockout is observed, not inferred.
                        "gating": False,
                    }
                )
                continue
            reading = {
                "provider": "ollama",
                "account": "default",
                "model": "*",
                "kind": window,
                "quotaId": window,
                "usedRatio": _clamp(used),
                "resetEpoch": reset,
                "durationSeconds": None,
                "source": source,
                "observedAtEpoch": now,
                "basis": BASIS_PROVIDER,
            }
        samples.append(("ghostship_ai_quota_used_ratio", labels, reading["usedRatio"]))
        if reading.get("resetEpoch") is not None:
            samples.append(
                ("ghostship_ai_quota_reset_timestamp_seconds", labels, reading["resetEpoch"])
            )
        samples.append(
            ("ghostship_ai_quota_observed_timestamp_seconds", labels, now)
        )
        samples.append(("ghostship_ai_quota_state", {**labels, "state": "measured"}, 1.0))
        windows.append(reading)
    if state_path:
        _save_window_state(state_path, _ollama_window_state(windows, previous))
    if not samples:
        return SourceResult(
            source=source,
            status="error",
            reason=codes.HTTP_ERROR if failures else codes.OK,
            duration_s=time.monotonic() - started,
        )
    return SourceResult(
        source=source,
        status="ok" if not failures else "partial",
        reason=codes.OK if not failures else codes.HTTP_ERROR,
        metrics=samples,
        observed_at=now,
        duration_s=time.monotonic() - started,
        windows=windows,
    )


def _ollama_balance_windows(
    body: Any, now: float, previous: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The session and the weekly window of the Ollama Cloud account.

    The balance endpoint publishes the share of the window that is left and
    the instant it resets. The used share is the rest of it. The length of
    the weekly window is a week; the length of the session window is learned
    from the step between two successive resets, because the provider
    publishes none.
    """
    if not isinstance(body, Mapping):
        return []
    included = body.get("included")
    included = included if isinstance(included, Mapping) else {}
    published = _ollama_published_length(included)
    windows: list[dict[str, Any]] = []
    for window in OLLAMA_WINDOWS:
        entry = included.get(window)
        if not isinstance(entry, Mapping):
            continue
        remaining = entry.get("remaining_percent")
        if not isinstance(remaining, (int, float)) or isinstance(remaining, bool):
            continue
        used = _clamp(1.0 - float(remaining) / 100.0)
        reset = iso_to_epoch(entry.get("resets_at"))
        duration, basis = _ollama_window_length(window, reset, published, previous)
        windows.append(
            {
                "provider": "ollama",
                "account": "default",
                "model": "*",
                "kind": window,
                "quotaId": window,
                "usedRatio": used,
                "resetEpoch": reset,
                "durationSeconds": duration,
                "source": "ollama",
                "observedAtEpoch": now,
                "basis": basis,
            }
        )
    return windows


def _ollama_published_length(included: Mapping[str, Any]) -> float | None:
    """The length of the allowance, when the provider publishes its period."""
    period = included.get("period")
    if not isinstance(period, Mapping):
        return None
    start = iso_to_epoch(period.get("from"))
    end = iso_to_epoch(period.get("until"))
    if start is None or end is None or end <= start:
        return None
    return float(end - start)


def _ollama_window_length(
    window: str,
    reset: float | None,
    published: float | None,
    previous: Mapping[str, Any],
) -> tuple[float | None, str]:
    """The length of one Ollama window, and the basis of that length.

    The weekly window resets on Monday, so it is a week long. The session
    window publishes no length: the step between two successive resets is
    what measures it, and until two resets have been seen the length is
    derived, never measured.
    """
    if window == "weekly":
        return OLLAMA_WEEKLY_SECONDS, BASIS_PROVIDER
    known = previous.get(window) if isinstance(previous, Mapping) else None
    known = known if isinstance(known, Mapping) else {}
    last_reset = known.get("reset_at")
    if (
        reset is not None
        and isinstance(last_reset, (int, float))
        and not isinstance(last_reset, bool)
        and float(reset) > float(last_reset)
    ):
        step = float(reset) - float(last_reset)
        if OLLAMA_MIN_WINDOW_SECONDS <= step <= OLLAMA_MAX_WINDOW_SECONDS:
            # Two successive resets: the step between them is the length of
            # the session window.
            return step, BASIS_PROVIDER_DERIVED
    duration = known.get("duration_seconds")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        if OLLAMA_MIN_WINDOW_SECONDS <= float(duration) <= OLLAMA_MAX_WINDOW_SECONDS:
            # The window has not reset since it was measured: its length is
            # the one that was measured then.
            return float(duration), BASIS_PROVIDER_DERIVED
    if published is not None:
        return published, BASIS_PROVIDER
    return OLLAMA_SESSION_SECONDS, BASIS_PROVIDER_DERIVED


def _ollama_window_state(
    windows: Iterable[Mapping[str, Any]], previous: Mapping[str, Any]
) -> dict[str, Any]:
    """The reset instants and the lengths of the windows, for the next read."""
    state: dict[str, Any] = {}
    for window in windows:
        kind = str(window.get("kind") or "")
        if kind not in OLLAMA_WINDOWS:
            continue
        reset = window.get("resetEpoch")
        duration = window.get("durationSeconds")
        state[kind] = {
            "reset_at": float(reset) if isinstance(reset, (int, float)) else None,
            "duration_seconds": (
                float(duration) if isinstance(duration, (int, float)) else None
            ),
        }
    return state

