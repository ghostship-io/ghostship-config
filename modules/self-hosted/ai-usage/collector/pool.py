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
import math
import os
import re
import socket
import sqlite3
import time
from pathlib import Path
from typing import Any

import codes
import quota as quota_module
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
    """The pool's own ceilings.

    These are the limits the pool enforces, which is a local policy and not
    the provider's own allowance. The basis they were read with is
    published with the `ghostship_ai_provider_limit` family, so a reader
    can tell the pool's ceiling from the provider's published number and
    from what the provider's headers said.
    """
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


# The provider whose response headers the pool records per model. Its own
# rate-limit headers name a window and a reset, and the window is the
# provider's capacity for that model, not the pool's admission cap.
REPORTED_PROVIDER = "groq"

# The scope Groq reports a per-model rate limit with. A reading of another
# scope is not a window of one model, and it is left to the diagnostics
# instead of being filed as capacity.
REPORTED_MODEL_SCOPE = "model_in_organization"

# The unit a reported window is measured in, the kind of window it is, and
# how long that window runs. The provider's headers name a rate limit, and
# the period it covers is the length of the window: requests per day refill
# every day, tokens per minute every minute. A unit this table does not
# name is not a window the collector knows how to file.
REPORTED_UNITS = {
    "rpd": ("daily", 86400.0),
    "tpm": ("minute", 60.0),
}

# The basis of a window read from the provider's own response headers.
BASIS_PROVIDER_REPORTED = "provider_reported"

_DURATION_TEXT = re.compile(r"(?:\d+(?:\.\d+)?(?:ms|s|m|h|d))+")
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)")
_DURATION_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _finite_number(value: Any) -> float | None:
    """A finite number, or None. A boolean is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _strict_duration_seconds(value: Any) -> float | None:
    """Parse a reset duration only when the whole value is one.

    The diagnostic reader is tolerant, so a provider string such as
    "2s garbage" still yields a number for the metrics. A capacity reading
    is not tolerant: the text has to be a duration on its own, because a
    reset the collector had to guess would invent headroom.
    """
    number = _finite_number(value)
    if number is not None:
        return number if number >= 0.0 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if _DURATION_NUMBER.fullmatch(text):
        return float(text)
    if not _DURATION_TEXT.fullmatch(text):
        return None
    parts = _DURATION_PART.findall(text)
    if not parts:
        return None
    scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    seconds = sum(float(part) * scale[unit] for part, unit in parts)
    return seconds if seconds >= 0.0 else None


def _reported_windows(status: dict[str, Any], now: float) -> list[dict[str, Any]]:
    """The windows a provider's own rate-limit headers reported, per model.

    The pool records the headers of a provider's answer as observations. A
    reading of one model inside the organization is that model's capacity:
    the share of the limit the provider says is used, the moment it refills,
    and the length of its window. The reading is never filed for the whole
    account, so one spent model does not lock out its siblings.

    The reset is the moment the provider reported, counted from the moment
    it observed the reading, and never from the collection time. A reading
    that has already refilled, or that is older than the collector's quota
    freshness bound, is not current capacity: it is dropped rather than
    published as headroom or as a lockout. A limit, a remaining count, a
    reset or an observation the reader cannot use gives no measured
    capacity, and nothing is filled in for it.
    """
    windows: list[dict[str, Any]] = []
    for row in status.get("quota_observations") or []:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if provider.lower() != REPORTED_PROVIDER or not model:
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        if str(data.get("scope") or "") != REPORTED_MODEL_SCOPE:
            continue
        observed = _finite_number(row.get("observed_at"))
        if observed is None:
            continue
        if observed > now + quota_module.FUTURE_TOLERANCE_SECONDS:
            continue
        if now - observed > quota_module.STALE_AFTER_SECONDS:
            continue
        units = data.get("windows") if isinstance(data.get("windows"), dict) else {}
        for unit, values in sorted(units.items()):
            period = REPORTED_UNITS.get(str(unit))
            if period is None or not isinstance(values, dict):
                continue
            kind, duration = period
            limit = _finite_number(values.get("limit"))
            remaining = _finite_number(values.get("remaining"))
            if limit is None or limit <= 0.0:
                continue
            if remaining is None or remaining < 0.0 or remaining > limit:
                continue
            refill = _strict_duration_seconds(values.get("reset"))
            if refill is None:
                continue
            reset = observed + refill
            if reset <= now:
                # The window the provider reported has already refilled.
                continue
            windows.append(
                {
                    "provider": provider,
                    "account": "default",
                    "model": model,
                    "kind": kind,
                    "quotaId": str(unit),
                    "usedRatio": 1.0 - remaining / limit,
                    "resetEpoch": reset,
                    "durationSeconds": duration,
                    "observedAtEpoch": observed,
                    "source": "free_pool",
                    "basis": BASIS_PROVIDER_REPORTED,
                    # The reading is the capacity of this model alone. Its
                    # scope is explicit, so the account keeps no window of
                    # the whole provider that every model would share.
                    "applies_to": (model,),
                }
            )
    return sorted(
        windows,
        key=lambda window: (
            window["provider"],
            window["model"],
            window["kind"],
            window["quotaId"],
        ),
    )


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
            # The capacity the provider itself reported, through its own
            # response headers. The pool's admission caps stay metrics and
            # never become a provider window.
            windows=_reported_windows(status, now),
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
        # The pool's own probe of the route. It says whether the route
        # answered its last check, the class of the answer, the model it
        # checked and the moment of the check. A probe the pool did not run
        # carries no moment and is not a reading of the route.
        probe = state.get("probe")
        if isinstance(probe, dict):
            probe_state = probe.get("state")
            probe_model = probe.get("model")
            if (
                isinstance(probe_state, str)
                and probe_state
                and isinstance(probe_model, str)
                and probe_model
            ):
                samples.append(
                    _pool_sample(
                        "ghostship_ai_pool_probe",
                        {
                            "provider": str(provider),
                            "model": probe_model,
                            "state": probe_state,
                            "category": str(probe.get("category") or ""),
                        },
                        1.0,
                    )
                )
                checked = probe.get("at")
                if isinstance(checked, (int, float)) and not isinstance(checked, bool):
                    samples.append(
                        _pool_sample(
                            "ghostship_ai_pool_probe_timestamp_seconds",
                            {"provider": str(provider), "model": probe_model},
                            float(checked),
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
        # The scope the provider reported the limit with. A per-model
        # reading keeps its model scope, so a reader never files one
        # model's limit as the limit of the whole account.
        scope = (
            "model"
            if str(data.get("scope") or "") == REPORTED_MODEL_SCOPE
            else "account"
        )
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
            # A limit the provider's own response headers carried is an
            # observation. It is published with the observed basis, beside
            # the pool's own ceiling and the provider's published number.
            observed_limit = values.get("limit")
            if isinstance(observed_limit, (int, float)) and not isinstance(
                observed_limit, bool
            ):
                samples.append(
                    _pool_sample(
                        "ghostship_ai_pool_observed_limit",
                        {
                            "provider": provider,
                            "model": model,
                            "limit": str(unit),
                            "scope": scope,
                        },
                        float(observed_limit),
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
    # The recent jobs are counted by their label set. A metric series is a
    # name with a label set, and two jobs that share a provider, a worker, a
    # client and a status are the same series: publishing one sample per
    # job published that series twice, the writer dropped the repeat, and
    # the published number was one where it was two. The series is the
    # count of those jobs, published once.
    recent_jobs: dict[tuple[str, str, str, str], int] = {}
    for job in status.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        provider = str(job.get("provider") or "")
        if not provider:
            continue
        key = (
            provider,
            str(job.get("worker") or "unknown"),
            str(job.get("client") or "default"),
            str(job.get("status") or "unknown"),
        )
        recent_jobs[key] = recent_jobs.get(key, 0) + 1
    for key in sorted(recent_jobs):
        provider, worker, client, job_status = key
        samples.append(
            _pool_sample(
                "ghostship_ai_pool_recent_jobs",
                {
                    "provider": provider,
                    "worker": worker,
                    "client": client,
                    "status": job_status,
                },
                float(recent_jobs[key]),
            )
        )
    updated = status.get("catalog_updated_at")
    if isinstance(updated, (int, float)):
        samples.append(
            _pool_sample("ghostship_ai_pool_catalog_updated_timestamp_seconds", {}, float(updated))
        )


def _emit_catalog(samples: list[Sample], catalog: dict[str, Any]) -> None:
    # The account limits of a provider belong to the provider, not to one of
    # its models, so they are published once per provider. A provider with
    # several models used to publish the same limit once per model, and the
    # repeated series made the scrape fail.
    emitted_account_limits: set[tuple[str, str]] = set()
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
            # The pool's own reason a candidate is unavailable. The pool
            # names the policy that parks the account or the route, and the
            # snapshot repeats that reason instead of guessing one. A
            # candidate that is offered carries none.
            unavailable_reason = candidate.get("unavailable_reason")
            if isinstance(unavailable_reason, str) and unavailable_reason:
                samples.append(
                    _pool_sample(
                        "ghostship_ai_pool_model_unavailable_reason",
                        {**labels, "reason": unavailable_reason},
                        1.0,
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
            # When the pool last sent a job to this route. The least recently
            # used route breaks the tie inside the quality band of the free
            # tier, so the reading is published with the route.
            last_used = candidate.get("last_used")
            if isinstance(last_used, (int, float)) and not isinstance(last_used, bool):
                samples.append(
                    _pool_sample(
                        "ghostship_ai_pool_route_last_used_timestamp_seconds",
                        labels,
                        float(last_used),
                    )
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
                    # The score the pool's own bench gave the route. It is
                    # the pool's measurement, not ours, and it is published
                    # beside the admission so a reader can see how strong it
                    # is.
                    score = (
                        entry_value.get("score") if isinstance(entry_value, dict) else None
                    )
                    if isinstance(score, (int, float)) and not isinstance(score, bool):
                        samples.append(
                            _pool_sample(
                                "ghostship_ai_pool_admission",
                                {**labels, "workload": str(workload)},
                                float(score),
                            )
                        )
            account_limits = candidate.get("account_limits")
            if isinstance(account_limits, dict):
                new_limits = {
                    name: value
                    for name, value in account_limits.items()
                    if (str(provider), str(name)) not in emitted_account_limits
                }
                if new_limits:
                    samples.extend(
                        _limit_samples(str(provider), "*", new_limits, "account")
                    )
                    for name in new_limits:
                        emitted_account_limits.add((str(provider), str(name)))
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
