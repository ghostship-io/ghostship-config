"""The free inference pool as a collection source.

The pool is the account set that serves free-tier models: nineteen provider
accounts and the models each of them may use. The broker exposes a read-only
surface over its Unix socket, and the pool's own ledger records what each
account spent.

Everything reported here is a local policy or a local observation. The pool's
limits are admission caps, not independently verified provider allowances, so
they are labelled as such and never presented as a provider's own quota.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import sqlite3
import time
from pathlib import Path
from typing import Any

import codes
from metrics import SourceResult, Sample

MAX_RESPONSE = 8 * 1024 * 1024
TIMEOUT = 30


class BridgeError(RuntimeError):
    """The free inference bridge could not be read."""


class UnixHttpConnection(http.client.HTTPConnection):
    """An HTTP connection over a Unix socket."""

    def __init__(self, path: str, timeout: float = TIMEOUT) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def bridge_call(socket_path: str, token: str, surface: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call the broker's read-only surface."""
    body = json.dumps({"surface": surface, "arguments": arguments}).encode()
    connection = UnixHttpConnection(socket_path)
    try:
        connection.request(
            "POST",
            "/v1/inference",
            body=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = response.read(MAX_RESPONSE + 1)
        if response.status != 200:
            raise BridgeError(f"bridge refused the request ({response.status})")
    except (OSError, http.client.HTTPException) as error:
        raise BridgeError("free inference bridge is unavailable") from error
    finally:
        connection.close()
    try:
        result = json.loads(payload)
    except ValueError as error:
        raise BridgeError("free inference bridge returned invalid JSON") from error
    if not isinstance(result, dict):
        raise BridgeError("free inference bridge returned an unexpected payload")
    return result


def resolve_socket(server_file: str | os.PathLike[str], home: str | os.PathLike[str] | None = None) -> str:
    """Return the broker socket path.

    The published bridge file names the socket the containers use. The host
    reaches the same broker through the container home, where the socket
    actually lives.
    """
    candidates: list[str] = []
    try:
        data = json.loads(Path(server_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        socket_path = data.get("socket")
        if isinstance(socket_path, str) and socket_path:
            candidates.append(socket_path)
    if home:
        candidates.append(
            str(
                Path(home)
                / ".local"
                / "state"
                / "ghostship-free-inference-bridge"
                / "socket"
                / "inference.sock"
            )
        )
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    if candidates:
        return candidates[0]
    raise BridgeError("free inference bridge has no socket path")


def resolve_token(token_file: str | os.PathLike[str], home: str | os.PathLike[str] | None = None) -> str:
    """Return the broker bearer token."""
    candidates = [str(token_file)]
    if home:
        candidates.append(
            str(Path(home) / ".local" / "state" / "ghostship-free-inference-bridge" / "token")
        )
    for candidate in candidates:
        try:
            token = Path(candidate).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if token:
            return token
    raise BridgeError("free inference bridge credential is unavailable")


def _pool_sample(name: str, labels: dict[str, str], value: float) -> Sample:
    return (name, labels, value)


def _limit_samples(provider: str, model: str, limits: Any, scope: str) -> list[Sample]:
    samples: list[Sample] = []
    if not isinstance(limits, dict):
        return samples
    for limit, value in sorted(limits.items()):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        samples.append(
            _pool_sample(
                "ghostship_ai_pool_limit",
                {"provider": provider, "model": model, "limit": str(limit), "scope": scope},
                float(value),
            )
        )
    return samples


def collect(
    server_file: str | os.PathLike[str],
    token_file: str | os.PathLike[str],
    ledger_path: str | os.PathLike[str] | None,
    now: float,
    home: str | os.PathLike[str] | None = None,
) -> list[SourceResult]:
    """Collect the pool's catalog, states, health, and ledger usage."""
    started = time.monotonic()
    source = "free_pool"
    try:
        socket_path = resolve_socket(server_file, home)
        token = resolve_token(token_file, home)
    except (OSError, ValueError, BridgeError) as error:
        return [
            SourceResult(
                source=source,
                status="missing_credentials",
                reason=codes.UNAVAILABLE,
                duration_s=time.monotonic() - started,
            )
        ]
    try:
        status = bridge_call(socket_path, token, "status", {"op": "status"})
        catalog = _read_catalog(socket_path, token)
    except BridgeError as error:
        return [
            SourceResult(
                source=source,
                status="error",
                reason=codes.UNAVAILABLE,
                duration_s=time.monotonic() - started,
            )
        ]
    samples: list[Sample] = []
    _emit_status(samples, status)
    _emit_catalog(samples, catalog)
    ledger = _read_ledger(ledger_path, now)
    samples.extend(ledger.samples)
    return [
        SourceResult(
            source=source,
            status="partial" if ledger.status != "ok" else "ok",
            reason=codes.OK if ledger.status == "ok" else ledger.reason,
            metrics=samples,
            observed_at=now,
            duration_s=time.monotonic() - started,
        )
    ]


def _read_catalog(socket_path: str, token: str) -> dict[str, Any]:
    """Page through the pool's model catalog."""
    merged: dict[str, Any] = {"providers": {}}
    offset = 0
    for _ in range(20):
        page = bridge_call(
            socket_path,
            token,
            "status",
            {"op": "models", "offset": offset, "limit": 50},
        )
        for provider, entry in (page.get("providers") or {}).items():
            target = merged["providers"].setdefault(provider, {"candidates": []})
            if isinstance(entry, dict):
                for key in ("preferred_model", "selected_model"):
                    if entry.get(key):
                        target[key] = entry[key]
                candidates = entry.get("candidates")
                if isinstance(candidates, list):
                    target["candidates"].extend(candidates)
        next_offset = page.get("next_offset")
        if next_offset is None:
            break
        offset = int(next_offset)
    return merged


def _emit_status(samples: list[Sample], status: dict[str, Any]) -> None:
    for provider, state in (status.get("provider_states") or {}).items():
        if not isinstance(state, dict):
            continue
        name = state.get("state")
        if not isinstance(name, str) or not name:
            continue
        samples.append(
            _pool_sample(
                "ghostship_ai_pool_provider_state",
                {"provider": str(provider), "state": name},
                1.0,
            )
        )
    for row in status.get("health") or []:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not provider:
            continue
        labels = {"provider": provider, "model": model}
        for kind, field in (("successes", "successes"), ("failures", "failures")):
            value = row.get(field)
            if isinstance(value, (int, float)):
                samples.append(
                    _pool_sample(
                        "ghostship_ai_pool_health_events",
                        {**labels, "result": kind},
                        float(value),
                    )
                )
        latency = row.get("latency")
        if isinstance(latency, (int, float)):
            samples.append(_pool_sample("ghostship_ai_pool_latency_seconds", labels, float(latency)))
        cooldown = row.get("cooldown")
        if isinstance(cooldown, (int, float)) and model == "*":
            # A provider wide pause. The per model cooldown comes from the
            # catalog, so it is not repeated here.
            samples.append(
                _pool_sample("ghostship_ai_pool_model_cooldown_until_seconds", labels, float(cooldown))
            )
    for row in status.get("quota_observations") or []:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        windows = data.get("windows") if isinstance(data.get("windows"), dict) else {}
        observed = row.get("observed_at")
        for unit, values in windows.items():
            if not isinstance(values, dict):
                continue
            for kind in ("limit", "remaining"):
                value = values.get(kind)
                if not isinstance(value, (int, float)):
                    continue
                samples.append(
                    _pool_sample(
                        "ghostship_ai_pool_quota_amount",
                        {
                            "provider": provider,
                            "model": model,
                            "kind": kind,
                            "unit": str(unit),
                        },
                        float(value),
                    )
                )
            reset = values.get("reset")
            if isinstance(reset, str) and reset:
                seconds = _duration_seconds(reset)
                if seconds is None and reset.replace(".", "", 1).isdigit():
                    seconds = float(reset)
                if seconds is not None:
                    base = observed if isinstance(observed, (int, float)) else 0.0
                    samples.append(
                        _pool_sample(
                            "ghostship_ai_pool_quota_reset_seconds",
                            {"provider": provider, "model": model, "unit": str(unit)},
                            base + seconds,
                        )
                    )
        if isinstance(observed, (int, float)):
            samples.append(
                _pool_sample(
                    "ghostship_ai_pool_quota_observed_timestamp_seconds",
                    {"provider": provider, "model": model},
                    float(observed),
                )
            )
    for row in status.get("concurrency") or []:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "")
        account = str(row.get("account") or "default")
        for kind, fields in (("current", ("current",)), ("limit", ("limit", "max"))):
            for field in fields:
                value = row.get(field)
                if isinstance(value, (int, float)):
                    samples.append(
                        _pool_sample(
                            "ghostship_ai_pool_concurrency",
                            {"provider": provider, "account": account, "kind": kind},
                            float(value),
                        )
                    )
                    break
    for job in status.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        provider = str(job.get("provider") or "")
        if not provider:
            continue
        samples.append(
            _pool_sample(
                "ghostship_ai_pool_recent_jobs",
                {
                    "provider": provider,
                    "worker": str(job.get("worker") or "unknown"),
                    "client": str(job.get("client") or "default"),
                    "status": str(job.get("status") or "unknown"),
                },
                1.0,
            )
        )
    updated = status.get("catalog_updated_at")
    if isinstance(updated, (int, float)):
        samples.append(
            _pool_sample("ghostship_ai_pool_catalog_updated_timestamp_seconds", {}, float(updated))
        )


def _emit_catalog(samples: list[Sample], catalog: dict[str, Any]) -> None:
    for provider, entry in (catalog.get("providers") or {}).items():
        if not isinstance(entry, dict):
            continue
        candidates = entry.get("candidates") or []
        selected = entry.get("selected_model")
        preferred = entry.get("preferred_model")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            model = str(candidate.get("model") or "")
            if not model:
                continue
            labels = {"provider": str(provider), "model": model}
            geography = candidate.get("geography") or {}
            family = ""
            developer = ""
            operator = ""
            if isinstance(geography, dict):
                family = str(geography.get("family") or "")
                developer = str(geography.get("developer_country") or "")
                operator = str(geography.get("operator_country") or "")
            samples.append(
                _pool_sample(
                    "ghostship_ai_pool_model_info",
                    {
                        "provider": str(provider),
                        "model": model,
                        "family": family,
                        "developer_country": developer,
                        "operator_country": operator,
                    },
                    1.0,
                )
            )
            available = candidate.get("available")
            samples.append(
                _pool_sample(
                    "ghostship_ai_pool_model_available",
                    labels,
                    1.0 if available else 0.0,
                )
            )
            samples.append(
                _pool_sample(
                    "ghostship_ai_pool_model_selected",
                    labels,
                    1.0 if model in (selected, preferred) else 0.0,
                )
            )
            cooldown = candidate.get("cooldown_until")
            if isinstance(cooldown, (int, float)):
                samples.append(
                    _pool_sample("ghostship_ai_pool_model_cooldown_until_seconds", labels, float(cooldown))
                )
            admissions = candidate.get("admissions")
            if isinstance(admissions, dict):
                for workload, entry_value in admissions.items():
                    admitted = entry_value.get("admitted") if isinstance(entry_value, dict) else None
                    samples.append(
                        _pool_sample(
                            "ghostship_ai_pool_model_admission",
                            {**labels, "workload": str(workload)},
                            1.0 if admitted else 0.0,
                        )
                    )
            samples.extend(
                _limit_samples(str(provider), "*", candidate.get("account_limits"), "account")
            )
            samples.extend(
                _limit_samples(str(provider), model, candidate.get("model_limits"), "model")
            )


class _Ledger:
    def __init__(self) -> None:
        self.samples: list[Sample] = []
        self.status = "ok"
        self.reason = codes.OK


def _duration_seconds(text: str) -> float | None:
    """Parse a duration such as "1m26.4s" into seconds."""
    import re

    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", text)
    if not parts:
        return None
    scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    return sum(float(value) * scale[unit] for value, unit in parts)


def _read_ledger(path: str | os.PathLike[str] | None, now: float) -> _Ledger:
    """Read the pool's reservation ledger over the reporting windows."""
    ledger = _Ledger()
    if not path:
        ledger.status = "unsupported"
        ledger.reason = codes.UNSUPPORTED
        return ledger
    if not Path(path).exists():
        ledger.status = "missing_credentials"
        ledger.reason = codes.MISSING_CREDENTIALS
        return ledger
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as error:
        ledger.status = "error"
        ledger.reason = codes.UNAVAILABLE
        return ledger
    windows = (("24h", 86400), ("7d", 7 * 86400), ("30d", 30 * 86400))
    try:
        for window, seconds in windows:
            rows = connection.execute(
                "SELECT provider, model, count(*), sum(input), sum(output), sum(usd) "
                "FROM inference_reservations WHERE at > ? GROUP BY provider, model",
                (now - seconds,),
            ).fetchall()
            for provider, model, requests, tokens_in, tokens_out, usd in rows:
                labels = {"provider": str(provider), "model": str(model), "window": window}
                samples = [
                    ("ghostship_ai_usage_tokens", "input", float(tokens_in or 0)),
                    ("ghostship_ai_usage_tokens", "output", float(tokens_out or 0)),
                    ("ghostship_ai_usage_cost_usd", "cost", float(usd or 0)),
                    ("ghostship_ai_pool_ledger_requests", "requests", float(requests or 0)),
                ]
                for name, kind, value in samples:
                    if value == 0 and name != "ghostship_ai_pool_ledger_requests":
                        continue
                    if name == "ghostship_ai_usage_tokens":
                        ledger.samples.append(
                            (
                                name,
                                {
                                    "provider": str(provider),
                                    "model": str(model),
                                    "kind": kind,
                                    "window": window,
                                    "source": "free_pool",
                                    "basis": "ledger_estimate",
                                },
                                value,
                            )
                        )
                    elif name == "ghostship_ai_usage_cost_usd":
                        ledger.samples.append(
                            (
                                name,
                                {
                                    "provider": str(provider),
                                    "model": str(model),
                                    "window": window,
                                    "source": "free_pool",
                                    "basis": "ledger_estimate",
                                },
                                value,
                            )
                        )
                    else:
                        ledger.samples.append((name, labels, value))
    except sqlite3.Error as error:
        ledger.status = "partial"
        ledger.reason = codes.UNAVAILABLE
    finally:
        connection.close()
    return ledger
