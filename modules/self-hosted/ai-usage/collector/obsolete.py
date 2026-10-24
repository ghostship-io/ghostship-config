"""The one allowed filter: an obsolete model, with the reason it is obsolete.

The owner allows exactly one filter on the candidate lists: "the only thing we
should filter are obsolete models we obviously would never use". A model is
obsolete in one of two ways:

* the public catalog marks it deprecated; or
* another model of the same provider, family and variant carries a newer
  major generation.

The second rule is deliberately narrow. It never spans providers, and a
variant only competes with the same variant (a "pro" model does not supersede
a "flash" model, a "mini" does not supersede a full one). A plain generation
with no variant is superseded by any newer generation of its family. It only
compares the major generation, so a point release such as `claude-opus-5-5`
does not hide `claude-opus-5`. Every model that is removed is published with
its reason and the model that supersedes it; nothing else is hidden.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

# A numeric token long enough to be a date code rather than a version. Model
# ids carry dates as `20251001` or `0902`; they are not generations.
_DATE = re.compile(r"^\d{4,8}$")
_VERSION = re.compile(r"^(?P<prefix>[a-z]*)(?P<version>\d+(?:\.\d+)?)$")


def _segments(model: str) -> list[str]:
    """The model's own name, split into lower-case tokens."""
    text = str(model or "").strip().lower()
    # A provider prefix is not part of the family.
    text = text.rsplit("/", 1)[-1]
    text = text.replace("@cf-", "").replace("@cf/", "")
    text = text.replace("_", ".").replace(":", "-")
    return [token for token in re.split(r"[-\s]+", text) if token]


def _is_date(token: str) -> bool:
    return bool(_DATE.fullmatch(token)) and (len(token) == 8 or token[:2] in ("19", "20"))


def lineage(model: str) -> tuple[str, str, int, tuple[int, int]] | None:
    """Return (family, variant, major, (major, minor)) for a versioned model.

    A model without a recognized version returns None and is never pruned by
    the generation rule.
    """
    tokens = _segments(model)
    for index, token in enumerate(tokens):
        match = _VERSION.fullmatch(token)
        if not match:
            continue
        version_text = match.group("version")
        parts = version_text.split(".")
        prefix = match.group("prefix")
        # An attached family such as `qwen3.8` keeps its name in the family;
        # a stand-alone version (`4.5`) is not part of the family.
        family_tokens = list(tokens[:index])
        if prefix and (not family_tokens or prefix not in ("v", "m", "k")):
            family_tokens.append(prefix)
        # A dashed generation such as `claude-opus-4-5` continues with the
        # following numeric tokens until a word, a date or a size token.
        following = index + 1
        while following < len(tokens):
            candidate = tokens[following]
            if not candidate.isdigit() or len(candidate) > 2 or _is_date(candidate):
                break
            parts.append(candidate)
            following += 1
        if not family_tokens:
            continue
        family = "-".join(family_tokens)
        variant = "-".join(
            token for token in tokens[following:]
            if not _is_date(token)
        )
        numbers = [int(part) for part in parts]
        major = numbers[0]
        minor = numbers[1] if len(numbers) > 1 else 0
        return family, variant, major, (major, minor)
    return None


def _status(catalog: Any, provider: str, model: str) -> str:
    """The catalog's status for one model, or an empty string."""
    getter = getattr(catalog, "model_status", None)
    if not callable(getter):
        return ""
    try:
        return str(getter(provider, model) or "").strip().lower()
    except Exception:  # pragma: no cover - a catalog without the model
        return ""


def classify(
    offered: Iterable[tuple[str, str]],
    catalog: Any = None,
) -> list[dict[str, Any]]:
    """Every offered model the filter removes, with its visible reason."""
    pairs = sorted({
        (str(provider), str(model))
        for provider, model in offered or ()
        if str(provider) and str(model)
    })
    statuses = {pair: _status(catalog, *pair) for pair in pairs}
    lineages = {pair: lineage(pair[1]) for pair in pairs}
    # The newest non-deprecated model of every provider/family/variant group
    # is the only thing that can supersede another model. A model without a
    # variant is a plain generation, so any newer generation of the family
    # supersedes it; a variant ("mini", "sol", "flash") is only superseded by
    # the same variant.
    newest: dict[tuple[str, str, str], tuple[int, tuple[int, int], str]] = {}
    family_newest: dict[tuple[str, str], tuple[int, tuple[int, int], str]] = {}
    for pair in pairs:
        if statuses[pair] == "deprecated":
            continue
        parsed = lineages[pair]
        if parsed is None:
            continue
        family, variant, major, version = parsed
        key = (pair[0], family, variant)
        current = newest.get(key)
        if current is None or version > current[1]:
            newest[key] = (major, version, pair[1])
        current = family_newest.get((pair[0], family))
        if current is None or version > current[1]:
            family_newest[(pair[0], family)] = (major, version, pair[1])
    records: list[dict[str, Any]] = []
    for pair in pairs:
        provider, model = pair
        parsed = lineages[pair]
        if statuses[pair] == "deprecated":
            records.append({
                "provider": provider,
                "model": model,
                "reason": "deprecated by the model catalog",
                "basis": "deprecated",
                "family": parsed[0] if parsed else "",
                "variant": parsed[1] if parsed else "",
                "generation": parsed[2] if parsed else None,
                "superseded_by": None,
            })
            continue
        if parsed is None:
            continue
        family, variant, major, _version = parsed
        winner = newest.get((provider, family, variant))
        if variant and winner is None:
            continue
        if not variant:
            family_winner = family_newest.get((provider, family))
            if family_winner is not None and (
                winner is None or family_winner[1] > winner[1]
            ):
                winner = family_winner
        if winner is None or winner[0] <= major:
            continue
        suffix = f" ({variant})" if variant else ""
        records.append({
            "provider": provider,
            "model": model,
            "reason": (
                f"superseded by {winner[2]}{suffix} in the {family} family"
            ),
            "basis": "generation",
            "family": family,
            "variant": variant,
            "generation": major,
            "superseded_by": winner[2],
        })
    return records
