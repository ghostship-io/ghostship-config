"""The 3D tier: which models are worth using for 3D printing work.

The dashboard ranks every model the host can serve into a "3d" tier: the
models worth using for 3D printing work. That ranking is a prior combined
with real usage.

The prior is a judgement we encode here, not a measurement. Antigravity's
Gemini, Claude and GPT-Sol lead, because 3D printing work needs strong
reasoning about geometry, long code sessions and patient iteration; a few
bulk models follow for the repetitive parts. The catalog description and
modalities nudge the prior further, and a preview or experimental model
loses a little of it.

The usage side is measured, by reading the provider session histories of our
own 3D printing projects. Only files inside a directory whose name mentions
`3dprint` are read, only for the last 30 days, and never more than a bounded
number of files. Nothing here writes, and no provider, container or runtime is
started, stopped or reconfigured.
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

# The prior weights: mostly how good the model is, partly how much it is used.
PRIOR_WEIGHT = 0.75
USAGE_WEIGHT = 0.25

# Tokens that saturate the usage half of the score.
USAGE_LOG_SCALE = 5.0

# The catalog provider keys a provider may hold. The catalog owns that map;
# a provider the catalog does not know is looked up under its own name.

# The Claude prior per model id pattern. Higher is better.
CLAUDE_PRIORS: tuple[tuple[str, float], ...] = (
    ("opus", 0.92),
    ("sonnet", 0.85),
    ("fable", 0.80),
    ("haiku", 0.70),
)

# The base prior per model family, by model id pattern. Higher is better.
BASE_PRIORS: tuple[tuple[str, float], ...] = (
    ("grok", 0.80),
    ("deepseek-thinking", 0.78),
    ("deepseek-pro", 0.80),
    ("deepseek-flash", 0.72),
    ("minimax", 0.80),
    ("kimi-k3", 0.75),
    ("glm", 0.70),
    ("qwen", 0.68),
    ("muse", 0.60),
    ("longcat", 0.65),
    ("mimo", 0.65),
    ("space-bunny", 0.50),
)

# Anything we do not know about is a mid-range model.
DEFAULT_PRIOR = 0.50
GPT_PRIOR = 0.75
GEMINI_PRO_PRIOR = 0.95
GEMINI_PRIOR = 0.88

# A description that mentions 3D work at all means the model knows the domain.
THREE_D_TEXT = re.compile(
    r"\b(3-?d|cad|stl|mesh(?:es)?|blender|spatial|geometry|engineering|physics)\b",
    re.IGNORECASE,
)

# A preview or experimental model is not yet a settled choice.
UNSETTLED_MARKERS = ("preview", "experimental")

# A model of the last four months is the current line of its family.
RECENT_MODEL_DAYS = 120.0

# A model that is older than this has been superseded.
OLD_MODEL_DAYS = 365.0

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


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


# --------------------------------------------------------------- Priors
def _gemini_prior(model_id: str) -> float:
    """The prior of a Gemini model."""
    if re.search(r"gemini[-_. ]?[34]", model_id):
        if "pro" in model_id:
            return GEMINI_PRO_PRIOR
    if "flash" in model_id:
        return GEMINI_PRIOR
    return GEMINI_PRIOR


def _base_prior(model_id: str) -> float:
    """The family prior of a model, before the catalog signals."""
    if "gemini" in model_id:
        return _gemini_prior(model_id)
    for marker, value in CLAUDE_PRIORS:
        if marker in model_id:
            return value
    if "gpt" in model_id:
        # GPT-Sol and GPT-Astra lead the other GPT models.
        if "sol" in model_id or "astra" in model_id:
            return 0.90
        return GPT_PRIOR
    for marker, value in BASE_PRIORS:
        if marker in model_id:
            return value
    return DEFAULT_PRIOR


def _description(entry: Mapping[str, Any]) -> str:
    """The human description a catalog entry carries."""
    parts: list[str] = []
    for key in ("description", "summary", "details", "about"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    return " ".join(parts)


def _has_image_input(entry: Mapping[str, Any]) -> bool:
    """True when the model takes an attachment or an image."""
    for key in ("attachment", "attachment_supported", "vision", "image_input"):
        if entry.get(key):
            return True
    for key in ("modalities", "input_modalities", "inputModalities"):
        value = entry.get(key)
        if isinstance(value, Mapping):
            value = value.get("input")
        if isinstance(value, (list, tuple)):
            if any("image" in str(item).lower() for item in value):
                return True
    return False


def three_d_prior(provider: str, model: str, entry: dict | None = None) -> float:
    """Return a 0..1 score of how good the model is at 3D printing work."""
    model_id = str(model or "").lower()
    score = _base_prior(model_id)
    if isinstance(entry, Mapping):
        if THREE_D_TEXT.search(_description(entry)):
            score += 0.05
        if _has_image_input(entry):
            score += 0.03
        # The current line of a model family knows 3D work better than the
        # line before it, and a model that is years old has not.
        age_days = _age_days(entry)
        if age_days is not None:
            if age_days <= RECENT_MODEL_DAYS:
                score += 0.05
            elif age_days > OLD_MODEL_DAYS:
                score -= 0.10
    if any(marker in model_id for marker in UNSETTLED_MARKERS):
        score -= 0.05
    return _clamp(score)


def _age_days(entry: Mapping[str, Any]) -> float | None:
    """The age of a catalog entry in days, or None when it is unknown."""
    value = entry.get("release_date")
    if not isinstance(value, str) or not value:
        return None
    try:
        released = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if released.tzinfo is None:
        released = released.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - released).total_seconds() / 86400.0


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
def three_d_score(prior: float, tokens: int) -> float:
    """The score the ranking engine consumes."""
    usage = min(1.0, math.log10(max(0, int(tokens)) + 1) / USAGE_LOG_SCALE)
    return PRIOR_WEIGHT * float(prior) + USAGE_WEIGHT * usage


def three_d_samples(
    provider: str,
    model: str,
    *,
    prior: float,
    tokens: int,
    now: float,
) -> list[tuple[str, dict[str, str], float]]:
    """Return the metrics for one model."""
    labels = {"provider": label_value(provider), "model": label_value(model)}
    score = three_d_score(prior, tokens)
    return [
        ("ghostship_ai_three_d_prior", dict(labels), float(prior)),
        ("ghostship_ai_three_d_usage_tokens", dict(labels), float(tokens)),
        ("ghostship_ai_three_d_score", dict(labels), score),
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
    """Return the 3D tier of every model: its prior, its usage and its score."""
    usage = collect_three_d_usage(home, now, max_files=max_files)
    keys = set(usage)
    for provider, model in _model_pairs(models):
        keys.add((provider, model))
    # The frontier models of a provider we already serve belong in the tier
    # too, so a model that is good at 3D work shows up before it is used.
    # Only the models of a family we score are listed; the rest of a
    # provider's catalog is not 3D work.
    for provider in sorted({provider for provider, _model in keys}):
        for model in _catalog_models(catalog, provider):
            if _base_prior(str(model).lower()) <= DEFAULT_PRIOR:
                continue
            keys.add((provider, model))
    rows: dict[tuple[str, str], dict] = {}
    for provider, model in sorted(keys):
        entry = _catalog_entry(catalog, provider, model)
        prior = three_d_prior(provider, model, entry)
        tokens = int(usage.get((provider, model), 0))
        rows[(provider, model)] = {
            "prior": prior,
            "tokens": tokens,
            "score": three_d_score(prior, tokens),
        }
    return rows
