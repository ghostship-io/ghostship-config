"""The Claude subscription windows, read from the Claude Code account.

T3 Code's Claude provider does not report its subscription windows on this
host: its limits probe answers ``probeFailed``. Claude Code itself reads the
account's usage through the OAuth session the CLI already holds, and the
collector reads the same endpoint with the same credential. That is a read:
the collector never refreshes or rotates the credential, never signs in, and
never changes the account.

The endpoint reports utilisation as a percentage of the five-hour session and
of the shared weekly window, with each reset instant. The collector publishes
both as provider-reported windows. A missing or expired credential is a
reason, never a zero.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

import codes
from metrics import Sample, SourceResult
from util import HttpResult, http_request, iso_to_epoch

SOURCE = "claude_usage"
PROVIDER = "claude"
DEFAULT_PATH = "/srv/apps/t3code/home/.claude/.credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
# The two windows the account reports. The weekly window is the shared pool
# that gates every Claude model; the five-hour window is the session line.
WINDOWS = (
    ("five_hour", "session", 5 * 3600.0),
    ("seven_day", "weekly", 7 * 86400.0),
)

HttpCall = Callable[..., HttpResult]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def read_credentials(path: str) -> tuple[str, float | None] | None:
    """The access token and its expiry, or None when the file is unusable.

    Only the two values the reader needs leave this function. The refresh
    token and every other field stay in the file.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    oauth = document.get("claudeAiOauth")
    if not isinstance(oauth, Mapping):
        return None
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token.strip():
        return None
    expires = _number(oauth.get("expiresAt"))
    if expires is not None and expires > 10_000_000_000:
        # The credential file stores milliseconds since the epoch.
        expires /= 1000.0
    return token.strip(), expires


def read(
    now: float,
    path: str = DEFAULT_PATH,
    *,
    http: HttpCall = http_request,
) -> SourceResult:
    """Read the two Claude windows from the account's OAuth usage endpoint."""
    credentials = read_credentials(path)
    if credentials is None:
        return SourceResult(
            source=SOURCE,
            status="missing_credentials",
            reason=codes.MISSING_CREDENTIALS,
        )
    token, expires = credentials
    if expires is not None and expires <= float(now):
        return SourceResult(
            source=SOURCE,
            status="expired_credentials",
            reason=codes.EXPIRED_CREDENTIALS,
            observed_at=float(now),
        )
    response = http(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": OAUTH_BETA,
            "Accept": "application/json",
        },
        timeout=30.0,
    )
    if not response.ok:
        return SourceResult(
            source=SOURCE,
            status="error",
            reason=codes.http_reason(response.status),
            observed_at=float(now),
        )
    body = response.json()
    if not isinstance(body, Mapping):
        return SourceResult(
            source=SOURCE,
            status="partial",
            reason=codes.INVALID_RESPONSE,
            observed_at=float(now),
        )
    samples: list[Sample] = []
    windows: list[dict[str, Any]] = []
    for window_id, kind, duration in WINDOWS:
        entry = body.get(window_id)
        if not isinstance(entry, Mapping):
            continue
        used = _number(entry.get("utilization"))
        if used is None:
            continue
        used_ratio = _clamp(used / 100.0)
        reset = iso_to_epoch(entry.get("resets_at"))
        labels = {
            "provider": PROVIDER,
            "account": "default",
            "model": "*",
            "window": kind,
            "quota": window_id,
            "source": SOURCE,
        }
        samples.append(("ghostship_ai_quota_used_ratio", dict(labels), used_ratio))
        samples.append(("ghostship_ai_quota_observed_timestamp_seconds", dict(labels), float(now)))
        if reset is not None:
            samples.append(("ghostship_ai_quota_reset_timestamp_seconds", dict(labels), reset))
        windows.append(
            {
                "provider": PROVIDER,
                "account": "default",
                "model": "*",
                "kind": kind,
                "quotaId": window_id,
                "usedRatio": used_ratio,
                "resetEpoch": reset,
                "durationSeconds": duration,
                "source": SOURCE,
                "observedAtEpoch": float(now),
                "basis": "provider_reported",
            }
        )
    if not windows:
        return SourceResult(
            source=SOURCE,
            status="partial",
            reason=codes.INVALID_RESPONSE,
            observed_at=float(now),
        )
    return SourceResult(
        source=SOURCE,
        status="ok" if len(windows) == len(WINDOWS) else "partial",
        reason=codes.OK,
        metrics=samples,
        observed_at=float(now),
        windows=windows,
    )
