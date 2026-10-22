"""Small shared helpers: HTTP with timeouts, secret-free env reading, clocks."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

DEFAULT_TIMEOUT = 20.0
USER_AGENT = "ghostship-ai-usage/1.0 (+collector)"

# A proxy environment would send provider traffic to an unexpected hop.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HttpResult:
    __slots__ = ("status", "body", "error")

    def __init__(self, status: int, body: bytes, error: str = "") -> None:
        self.status = status
        self.body = body
        self.error = error

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and not self.error


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> HttpResult:
    """Perform one bounded HTTP request. Never raises for network failures."""
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return HttpResult(response.status, response.read(4 * 1024 * 1024))
    except urllib.error.HTTPError as error:
        try:
            payload = error.read(64 * 1024)
        except Exception:  # pragma: no cover - defensive
            payload = b""
        return HttpResult(error.code, payload, f"http {error.code}")
    except (urllib.error.URLError, OSError, ValueError) as error:
        return HttpResult(0, b"", type(error).__name__)


def read_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Read a KEY=VALUE file. Values never leave this process."""
    values: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def now() -> float:
    return time.time()


def iso_to_epoch(value: str | None) -> float | None:
    """Parse an ISO-8601 timestamp into epoch seconds."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        from datetime import timezone

        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def day_string(epoch: float, offset_seconds: float = 0.0) -> str:
    """Return the UTC day (YYYY-MM-DD) for an epoch timestamp."""
    from datetime import datetime, timedelta, timezone

    moment = datetime.fromtimestamp(epoch + offset_seconds, tz=timezone.utc)
    return moment.strftime("%Y-%m-%d")


def account_alias(provider: str, account: str | None) -> str:
    """Reduce an account identifier to a non-secret alias.

    Emails and raw account identifiers never reach a metric label.
    """
    if not account:
        return "default"
    text = str(account)
    if "@" in text:
        local, _, domain = text.partition("@")
        return f"{provider}-{(local or 'account')[:8]}" if local else provider
    if len(text) > 40:
        return f"{provider}-{abs(hash(text)) % 100000:05d}"
    return f"{provider}-{text}"[:60]
