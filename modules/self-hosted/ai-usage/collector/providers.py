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
* Ollama: the Ollama Cloud usage endpoint.

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
from typing import Any, Callable

from metrics import SourceResult, Sample
from util import HttpResult, http_request, iso_to_epoch, read_env_file

HttpCall = Callable[..., HttpResult]

GROK_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
OPENCODE_GO_USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
OLLAMA_USAGE_URL = "https://ollama.com/api/usage"
ANTIGRAVITY_ENDPOINTS = (
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
)
ANTIGRAVITY_USER_AGENT = (
    "antigravity/hub/1.0.0 (aidev_client; os_type=linux; arch=arm64; cl=963137146)"
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


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
            detail="no Grok CLI credential",
            duration_s=time.monotonic() - started,
        )
    response = http(GROK_BILLING_URL, headers={"Authorization": f"Bearer {token}"})
    if not response.ok:
        return SourceResult(
            source=source,
            status="error",
            detail=f"billing request failed ({response.status or response.error})",
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
            detail="billing response carried no usage period",
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
            detail="no OpenCode Console credential",
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
            detail=f"usage request failed ({response.status or response.error})",
            duration_s=time.monotonic() - started,
        )
    body = response.json() or {}
    usage = body.get("usage") if isinstance(body, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    if not usage:
        return SourceResult(
            source=source,
            status="partial",
            detail="usage response carried no windows",
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
            detail="no Antigravity account token",
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
            detail="Antigravity account token is unreadable",
            duration_s=time.monotonic() - started,
        )
    access = _antigravity_access_token(token, http)
    if not access:
        return SourceResult(
            source=source,
            status="error",
            detail="Antigravity token refresh failed",
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
            detail="Antigravity returned no quota data",
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
        detail="" if not failures else f"{failures} Antigravity requests failed",
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
def read_openrouter(
    env_path: str | os.PathLike[str], now: float, http: HttpCall = http_request
) -> SourceResult:
    started = time.monotonic()
    source = "openrouter"
    key = read_env_file(env_path).get("OPENROUTER_API_KEY", "")
    if not key:
        return SourceResult(
            source=source,
            status="missing_credentials",
            detail="no OpenRouter API key",
            duration_s=time.monotonic() - started,
        )
    headers = {"Authorization": f"Bearer {key}"}
    credits = http(OPENROUTER_CREDITS_URL, headers=headers)
    account = http(OPENROUTER_KEY_URL, headers=headers)
    if not (credits.ok or account.ok):
        return SourceResult(
            source=source,
            status="error",
            detail=f"OpenRouter request failed ({credits.status or account.status})",
            duration_s=time.monotonic() - started,
        )
    samples: list[Sample] = []
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
        metrics=samples,
        observed_at=now,
        duration_s=time.monotonic() - started,
    )


# --------------------------------------------------------------- Ollama
def read_ollama(
    env_path: str | os.PathLike[str], now: float, http: HttpCall = http_request
) -> SourceResult:
    started = time.monotonic()
    source = "ollama"
    key = read_env_file(env_path).get("OLLAMA_API_KEY", "")
    if not key:
        return SourceResult(
            source=source,
            status="missing_credentials",
            detail="no Ollama API key",
            duration_s=time.monotonic() - started,
        )
    headers = {"Authorization": f"Bearer {key}"}
    samples: list[Sample] = []
    failures = 0
    for window, range_value in (("24h", "24h"), ("7d", "7d"), ("30d", "30d")):
        response = http(f"{OLLAMA_USAGE_URL}?range={range_value}", headers=headers)
        if not response.ok:
            failures += 1
            continue
        body = response.json() or {}
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
    if not samples:
        return SourceResult(
            source=source,
            status="error",
            detail=f"Ollama usage request failed ({failures} attempts)",
            duration_s=time.monotonic() - started,
        )
    return SourceResult(
        source=source,
        status="ok" if not failures else "partial",
        metrics=samples,
        observed_at=now,
        duration_s=time.monotonic() - started,
    )
