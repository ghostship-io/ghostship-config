"""The 3D tier: the measured evidence behind it.

The tier admits a model only on explicit evidence: the catalog proves the
model accepts image input, and the model's workload admission for 3D work is
verified. There is no family prior, no catalog nudge, no age bonus and no
blended score: those were judgements encoded as numbers, and the owner
removed them.

The usage side is measured, by reading the provider session histories of our
own 3D printing projects. Only files inside a directory whose name mentions
`3dprint` are read, only for the last 30 days, and never more than a bounded
number of files. Nothing here writes, and no provider, container or runtime is
started, stopped or reconfigured. The usage is displayed beside the evidence
and never stands in for it.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

try:  # The collector adds its own directory to the import path.
    from catalog import PROVIDER_ALIASES as CATALOG_PROVIDER_ALIASES
    from metrics import label_value
except ImportError:  # pragma: no cover - imported outside the collector
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from catalog import PROVIDER_ALIASES as CATALOG_PROVIDER_ALIASES
    from metrics import label_value

# Session histories, and the provider each one's files belong to.
SESSION_ROOTS: tuple[tuple[str, str], ...] = (
    ("claude", ".claude/projects"),
    ("codex", ".codex/sessions"),
    ("grok", ".grok/sessions"),
    ("pi", ".pi/agent/sessions"),
)

# Only histories of our own 3D printing projects count.
THREE_D_MARKER = "3dprint"

# Session files older than this are not evidence of current usage.
MAX_FILE_AGE_SECONDS = 30 * 24 * 60 * 60

# How many session files one collection may read.
DEFAULT_MAX_FILES = 400

# The 3D tier no longer carries a prior or a blended score. The tier admits a
# model only on explicit evidence: the catalog proves it can read an image,
# and the workload admission of the model is verified. The measured usage
# below is displayed beside that evidence and never stands in for it.

# Tokens that saturate the displayed usage bar.
USAGE_LOG_SCALE = 5.0

# The token fields a usage object may report.
TOKEN_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

MODEL_KEYS: tuple[str, ...] = ("model", "model_id", "modelId")
USAGE_KEYS: tuple[str, ...] = ("usage", "token_usage", "tokens", "tokenUsage")


def visual_capable(entry: dict | None) -> bool:
    """True when the catalog proves the model accepts image input.

    A generic attachment flag, a model family name, and a token count are not
    proof: 3D work needs a model that can look at a drawing or a photograph,
    and only the catalog's own image-input modality says so.
    """
    if not isinstance(entry, Mapping):
        return False
    modalities = entry.get("modalities")
    if not isinstance(modalities, Mapping):
        return False
    inputs = modalities.get("input")
    if not isinstance(inputs, list):
        return False
    return any(str(value).lower() == "image" for value in inputs)


# ---------------------------------------------------------------- Usage
# ---------------------------------------------------------------- Usage
def _read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield the well-formed records of one JSONL file."""
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                # A malformed line is ignored, never fatal.
                continue
            if isinstance(record, dict):
                yield record


def _token_count(usage: Mapping[str, Any]) -> int:
    """The sum of every token kind one usage object reports."""
    total = 0
    detailed = False
    for key in TOKEN_FIELDS:
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        total += int(value)
        detailed = True
    if not detailed:
        value = usage.get("total_tokens")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # Only a total was reported: it is the input plus the output.
            total += int(value)
    return max(0, total)


def _parse_claude(path: Path) -> dict[str, int]:
    """Tokens per model in one Claude Code session file.

    Claude Code writes an assistant message more than once while it streams,
    and the same message can be repeated with the same usage. Counting every
    copy inflates the total, so a message is counted once with its largest
    reported usage.
    """
    totals: dict[str, int] = {}
    counted: dict[str, tuple[str, int]] = {}
    for record in _read_jsonl(path):
        message = record.get("message")
        if not isinstance(message, Mapping):
            continue
        model = message.get("model")
        usage = message.get("usage")
        if not isinstance(model, str) or not model:
            continue
        if not isinstance(usage, Mapping):
            continue
        count = _token_count(usage)
        if not count:
            continue
        key = message.get("id")
        if not isinstance(key, str) or not key:
            totals[model] = totals.get(model, 0) + count
            continue
        previous = counted.get(key)
        if previous is None:
            counted[key] = (model, count)
            continue
        if previous[0] == model:
            if count > previous[1]:
                counted[key] = (model, count)
        else:
            totals[previous[0]] = totals.get(previous[0], 0) + previous[1]
            counted[key] = (model, count)
    for model, count in counted.values():
        totals[model] = totals.get(model, 0) + count
    return totals


def _codex_usage(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The usage a Codex token count record reports, if it reports one."""
    holders: list[Mapping[str, Any]] = []
    payload = record.get("payload")
    if isinstance(payload, Mapping):
        holders.append(payload)
    holders.append(record)
    for holder in holders:
        kind = holder.get("type")
        if kind is not None and kind != "token_count":
            continue
        info = holder.get("info")
        if isinstance(info, Mapping):
            for key in ("last_token_usage", "total_token_usage"):
                usage = info.get(key)
                if isinstance(usage, Mapping) and usage:
                    return usage
        for key in ("last_token_usage", "total_token_usage"):
            usage = holder.get(key)
            if isinstance(usage, Mapping) and usage:
                return usage
    return None


def _parse_codex(path: Path) -> dict[str, int]:
    """Tokens per model in one Codex rollout file.

    Codex reports a token count after every turn and repeats the same count
    while a turn settles, so only a count that moved is counted.
    """
    totals: dict[str, int] = {}
    model = ""
    previous_total: tuple[str, int, int] | None = None
    for record in _read_jsonl(path):
        if record.get("type") == "turn_context":
            payload = record.get("payload")
            if isinstance(payload, Mapping):
                name = payload.get("model")
                if isinstance(name, str) and name:
                    model = name
            continue
        usage = _codex_usage(record)
        if usage is None or not model:
            continue
        count = _token_count(usage)
        if not count:
            continue
        total = _codex_total(record)
        if total is not None:
            fingerprint = (model, total[0], total[1])
            if fingerprint == previous_total:
                continue
            previous_total = fingerprint
        totals[model] = totals.get(model, 0) + count
    return totals


def _codex_total(record: Mapping[str, Any]) -> tuple[int, int] | None:
    """The cumulative input and output a Codex token count reports."""
    holders: list[Mapping[str, Any]] = []
    payload = record.get("payload")
    if isinstance(payload, Mapping):
        holders.append(payload)
    holders.append(record)
    for holder in holders:
        info = holder.get("info")
        if not isinstance(info, Mapping):
            continue
        total = info.get("total_token_usage")
        if isinstance(total, Mapping):
            inputs = total.get("input_tokens")
            outputs = total.get("output_tokens")
            if isinstance(inputs, (int, float)) and isinstance(outputs, (int, float)):
                return int(inputs), int(outputs)
    return None


def _model_and_usage(record: Mapping[str, Any]) -> tuple[str, Mapping[str, Any] | None]:
    """The model and the usage object one Grok or Pi record carries."""
    containers: list[Mapping[str, Any]] = [record]
    for key in ("message", "payload", "response", "data"):
        nested = record.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)
    model = ""
    for container in containers:
        for key in MODEL_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value:
                model = value
                break
        if model:
            break
    usage: Mapping[str, Any] | None = None
    for container in containers:
        for key in USAGE_KEYS:
            value = container.get(key)
            if isinstance(value, Mapping):
                usage = value
                break
        if usage:
            break
    return model, usage


def _parse_generic(path: Path) -> dict[str, int]:
    """Tokens per model in one Grok or Pi session file."""
    totals: dict[str, int] = {}
    for record in _read_jsonl(path):
        model, usage = _model_and_usage(record)
        if not model or usage is None:
            continue
        count = _token_count(usage)
        if count:
            totals[model] = totals.get(model, 0) + count
    return totals


def _parse_file(provider: str, path: Path) -> dict[str, int]:
    """Tokens per model in one session file of one provider."""
    if provider == "claude":
        return _parse_claude(path)
    if provider == "codex":
        return _parse_codex(path)
    return _parse_generic(path)


def _is_three_d_path(path: Path) -> bool:
    """True when the file sits in a directory that names a 3D project."""
    return THREE_D_MARKER in str(path.parent).lower()


def collect_three_d_usage(
    home: str,
    now: float,
    *,
    max_files: int = DEFAULT_MAX_FILES,
) -> dict[tuple[str, str], int]:
    """Return tokens used per (provider, model) by 3D printing projects."""
    totals: dict[tuple[str, str], int] = {}
    base = Path(home)
    read = 0
    for provider, relative in SESSION_ROOTS:
        root = base / relative
        if not root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            if THREE_D_MARKER not in dirpath.lower():
                continue
            for name in sorted(filenames):
                if not name.endswith(".jsonl"):
                    continue
                path = Path(dirpath) / name
                if not _is_three_d_path(path):
                    continue
                if read >= max_files:
                    return totals
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if now - stat.st_mtime > MAX_FILE_AGE_SECONDS:
                    continue
                read += 1
                for model, count in _parse_file(provider, path).items():
                    key = (provider, model)
                    totals[key] = totals.get(key, 0) + count
    return totals


# --------------------------------------------------------------- Catalog
def _catalog_document(catalog: Any) -> Mapping[str, Any]:
    """The catalog document, whether it is a Catalog or a plain mapping."""
    if catalog is None:
        return {}
    document = getattr(catalog, "document", None)
    if isinstance(document, Mapping):
        return document
    if isinstance(catalog, Mapping):
        return catalog
    return {}


def _provider_keys(provider: str) -> tuple[str, ...]:
    """The catalog provider keys that may hold this collector provider."""
    keys = [provider]
    for alias in CATALOG_PROVIDER_ALIASES.get(provider, ()):
        if alias not in keys:
            keys.append(alias)
    return tuple(keys)


def _primary_catalog_key(provider: str) -> str:
    """The catalog provider key that holds this provider's own models.

    The catalog's fallback keys carry the newest models of every provider,
    so they are used to find one model, never to list a provider's models.
    """
    aliases = CATALOG_PROVIDER_ALIASES.get(provider, ())
    return aliases[0] if aliases else provider


def _catalog_models(catalog: Any, provider: str) -> dict[str, Any]:
    """The catalog entries of one provider."""
    document = _catalog_document(catalog)
    for name in (provider, _primary_catalog_key(provider)):
        entry = document.get(name)
        if not isinstance(entry, Mapping) or not entry:
            continue
        models = entry.get("models")
        if isinstance(models, Mapping):
            return dict(models)
        if all(isinstance(value, Mapping) for value in entry.values()):
            return dict(entry)
    return {}


def _catalog_entry(catalog: Any, provider: str, model: str) -> dict | None:
    """The catalog entry of one model, when the catalog knows it."""
    document = _catalog_document(catalog)
    for name in _provider_keys(provider):
        entry = document.get(name)
        if not isinstance(entry, Mapping):
            continue
        models = entry.get("models")
        if not isinstance(models, Mapping):
            models = entry
        found = models.get(model)
        if isinstance(found, Mapping):
            return dict(found)
    return None


def _model_pairs(models: Any) -> list[tuple[str, str]]:
    """Every (provider, model) pair the caller knows about."""
    pairs: list[tuple[str, str]] = []
    if not models:
        return pairs
    if isinstance(models, Mapping):
        for key, value in models.items():
            if isinstance(key, (tuple, list)) and len(key) >= 2:
                pairs.append((str(key[0]), str(key[1])))
            elif isinstance(value, Mapping):
                provider = str(value.get("provider") or "")
                model = str(value.get("model") or value.get("id") or "")
                if provider and model:
                    pairs.append((provider, model))
        return pairs
    for item in models:
        if isinstance(item, Mapping):
            provider = str(item.get("provider") or "")
            model = str(item.get("model") or item.get("id") or "")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            provider = str(item[0])
            model = str(item[1])
        else:
            continue
        if provider and model:
            pairs.append((provider, model))
    return pairs


# --------------------------------------------------------------- Ranking
def three_d_samples(
    provider: str,
    model: str,
    *,
    tokens: int,
    now: float,
) -> list[tuple[str, dict[str, str], float]]:
    """Return the measured 3D usage of one model.

    There is no prior and no blended score: the two removed series were a
    judgement and a blend of a judgement with usage. The usage tokens are
    measured, and the tier orders by the verified record.
    """
    labels = {"provider": label_value(provider), "model": label_value(model)}
    return [
        ("ghostship_ai_three_d_usage_tokens", dict(labels), float(tokens)),
        ("ghostship_ai_three_d_observed_timestamp_seconds", dict(labels), float(now)),
    ]


def collect(
    home: str,
    catalog: Any,
    models: Any,
    now: float,
    *,
    max_files: int = DEFAULT_MAX_FILES,
) -> dict[tuple[str, str], dict]:
    """Return the measured 3D usage of every model we serve.

    The catalog check stays here because it is a fact about the model (does
    it read an image); the admission itself is explicit and verified, and
    this module never turns a family name into a score.
    """
    usage = collect_three_d_usage(home, now, max_files=max_files)
    keys = set(usage)
    for provider, model in _model_pairs(models):
        keys.add((provider, model))
    rows: dict[tuple[str, str], dict] = {}
    for provider, model in sorted(keys):
        entry = _catalog_entry(catalog, provider, model)
        rows[(provider, model)] = {
            "tokens": int(usage.get((provider, model), 0)),
            "visual": visual_capable(entry),
        }
    return rows
