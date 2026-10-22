"""Bind a provider model to its exact Artificial Analysis record.

A provider model id and an Artificial Analysis record are not the same string:
the provider adds routing namespaces, promotion markers, checkpoint dates and
effort suffixes, the feed writes dots as dashes, and a record exists once per
measured reasoning variant. A name equality lookup therefore misses legitimate
records, and a fuzzy match could borrow the score of a different model.

The binding here is exact on the model's own identity tokens:

* tokenization splits the id at separators and at letter/digit boundaries, so
  ``solar-pro3`` and ``Solar Pro 3`` are the same tokens, and so are
  ``gpt-6.1-sol`` and ``GPT-6.1 Sol``;
* identity tokens drop the reasoning variant words (``reasoning``, ``high``,
  ``max``, ...), because a variant is a measurement condition, not a model;
* the following are routing or packaging wrappers, not identity: a path
  namespace (``nvidia/``, ``@cf/google/``), a promotion marker (``:free``,
  ``-free``), an instruction-tuned packaging suffix (``-it``), and one leading
  vendor brand token (``meta``, ``nvidia``, ...);
* a checkpoint or release marker must match the record: its slug or name when
  it is a short checkpoint (``1017``, ``0309``), its ``release_date`` when it
  is a date (``20250929``, ``2024-11-20``);
* a documented alias table resolves the few models the official sources name
  differently, and every alias entry names its evidence.

Anything else is unknown: no record is borrowed, no score is invented, and the
coverage row says which rule refused it. The match never uses a substring test:
the identity token multisets must be equal.

The reasoning variant travels with the record. Artificial Analysis measures a
model under one effort setting, and a model that runs at another effort is not
the same measurement: the binding says whether the native variant matches the
measured one and lists the variants the feed published, so a recommendation can
align the native options when the model supports the measured setting.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Mapping

# The variant markers the feed puts in a record name or at the end of a slug,
# and the native option values they correspond to.
VARIANT_MARKERS = {
    "max": "max",
    "xhigh": "xhigh",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "minimal": "minimal",
    "thinking": "reasoning",
    "reasoning": "reasoning",
    "nonreasoning": "none",
    "non-reasoning": "none",
    "none": "none",
}

# Words that describe the measurement condition, not the model identity.
VARIANT_WORDS = {
    "reasoning",
    "thinking",
    "non",
    "none",
    "max",
    "xhigh",
    "high",
    "medium",
    "low",
    "minimal",
    "effort",
    "default",
    "fallback",
}

# Suffixes the provider layers on top of the model identity.
PROMOTION_SUFFIXES = (
    ":free",
    "-free",
    "_free",
    ":promo",
    "-promo",
    "_promo",
    "-contributor",
    "_contributor",
    ":contributor",
)
PACKAGING_SUFFIXES = ("-it", "_it", ":it")

# Vendor brand tokens that a record or a provider id may or may not carry.
VENDOR_WORDS = {
    "meta",
    "nvidia",
    "google",
    "microsoft",
    "anthropic",
    "openai",
    "alibaba",
    "amazon",
    "cohere",
    "mistral",
    "moonshot",
    "zai",
    "xai",
    "deepseek",
    "qwen",
    "poolside",
    "liquid",
    "upstage",
    "nousresearch",
}

# Official identity evidence for the few models whose names differ between the
# provider and the feed. Nothing is inferred from a shared word.
KNOWN_ALIASES = {
    # The Ollama Cloud listing calls it Beam; Artificial Analysis publishes the
    # same model as reflection-beam (artificialanalysis.ai/articles/reflection-beam).
    "beam": "reflection-beam",
    "beam-1-0-501b-a23b": "reflection-beam",
    "beam 1.0 501b a23b": "reflection-beam",
}

# Models the official evidence describes as text only, whatever a catalog
# modality field says. The source of each line is the article that measured it.
TEXT_ONLY_EVIDENCE = {
    "reflection-beam": "Artificial Analysis, Reflection Beam: text only",
    "beam": "Artificial Analysis, Reflection Beam: text only",
}

CHECKPOINT_TOKEN = re.compile(r"(?:^|[-_:])(\d{4}|\d{8})$")
DATE_SUFFIX = re.compile(r"(?:^|[-_])(\d{4})-?(\d{2})-?(\d{2})$")


def slugify(name: str) -> str:
    """The feed's slug of a model id."""
    text = str(name or "").strip().lower()
    text = re.sub(r"[.:/_ ]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def tokens(text: str) -> list[str]:
    """Identity tokens: case folded, split at separators and digit boundaries."""
    value = str(text or "").lower()
    value = re.sub(r"([a-z])([0-9])", r"\1 \2", value)
    value = re.sub(r"([0-9])([a-z])", r"\1 \2", value)
    return [part for part in re.split(r"[^a-z0-9]+", value) if part]


def identity(text: str) -> tuple[str, ...]:
    """The model identity, without the measurement condition words."""
    return tuple(sorted(part for part in tokens(text) if part not in VARIANT_WORDS))


def name_key(name: str) -> str:
    """A display name without its separators or case."""
    return "".join(character for character in str(name or "").lower() if character.isalnum())


def _variant_of_tokens(parts: list[str]) -> str:
    for marker in ("non-reasoning", "nonreasoning", "reasoning", "thinking", "xhigh", "high", "medium", "low", "minimal", "max"):
        marker_tokens = tokens(marker)
        if parts[-len(marker_tokens) :] == marker_tokens:
            return VARIANT_MARKERS.get(marker, "")
    return ""


def variant_of(name: str) -> tuple[str, str]:
    """The display name of a record and its variant marker, if it has one."""
    text = str(name or "").strip()
    match = re.search(r"\(([^)]+)\)\s*$", text)
    if match:
        for part in match.group(1).split(","):
            key = part.strip().lower()
            if key in VARIANT_MARKERS:
                return text[: match.start()].strip(), VARIANT_MARKERS[key]
    parts = tokens(text)
    marker = _variant_of_tokens(parts) if parts else ""
    if marker:
        base_tokens = parts[: len(parts) - len(tokens(_marker_text(marker)))]
        return " ".join(base_tokens), marker
    return text, ""


def _marker_text(variant: str) -> str:
    if variant == "none":
        return "nonreasoning"
    return variant


def native_variant(options: Any) -> str:
    """The reasoning variant a model runs with, from its native options."""
    if not isinstance(options, list):
        return ""
    for option in options:
        if not isinstance(option, Mapping):
            continue
        name = str(option.get("id") or "").lower()
        value = option.get("current_value")
        if name in ("variant", "reasoningeffort", "effort", "thinking") and isinstance(value, str):
            key = value.strip().lower()
            return VARIANT_MARKERS.get(key, key if key in VARIANT_MARKERS.values() else "")
    return ""


def can_align(options: Any, variant: str) -> bool:
    """True when the native options offer the measured variant."""
    if not variant:
        return False
    if not isinstance(options, list):
        return False
    for option in options:
        if not isinstance(option, Mapping):
            continue
        name = str(option.get("id") or "").lower()
        if name not in ("variant", "reasoningeffort", "effort", "thinking"):
            continue
        values = option.get("values") or option.get("allowed") or option.get("options")
        if isinstance(values, list):
            normalised = {str(value).strip().lower() for value in values}
            if variant in normalised or VARIANT_MARKERS.get(variant) in normalised:
                return True
    return False


def _strip_suffix(text: str, suffixes: Iterable[str]) -> str:
    value = str(text or "").strip().lower()
    for suffix in suffixes:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _id_forms(model: str) -> tuple[list[str], str, str]:
    """The identity forms of a provider model id, its vendor and its date.

    The date is either a full release date (``20250929`` or ``2024-11-20``) or
    a short checkpoint token (``1017``, ``0309``).
    """
    raw = str(model or "").strip().lower()
    vendor = ""
    if "/" in raw:
        parts = raw.split("/")
        vendor = parts[-2] if len(parts) > 1 else ""
        raw = parts[-1]
    raw = raw.strip("/")
    date = ""
    match = DATE_SUFFIX.search(raw)
    if match:
        date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        raw = raw[: match.start()]
    else:
        match = CHECKPOINT_TOKEN.search(raw)
        if match:
            token = match.group(1)
            if len(token) == 8 and 2000 <= int(token[:4]) <= 2035:
                date = f"{token[:4]}-{token[4:6]}-{token[6:]}"
            else:
                date = token
            raw = raw[: match.start()]
    forms = [raw, _strip_suffix(raw, PROMOTION_SUFFIXES), _strip_suffix(raw, PACKAGING_SUFFIXES)]
    stripped = _strip_suffix(raw, PROMOTION_SUFFIXES)
    forms.append(_strip_suffix(stripped, PACKAGING_SUFFIXES))
    seen: list[str] = []
    for form in forms:
        form = form.strip("-_")
        if form and form not in seen:
            seen.append(form)
    aliased: list[str] = []
    for form in seen:
        alias = KNOWN_ALIASES.get(form) or KNOWN_ALIASES.get(slugify(form))
        if alias and alias not in seen and alias not in aliased:
            aliased.append(alias)
    return seen + aliased, vendor, date


def _identity_tokens(text: str) -> list[str]:
    """The ordered identity tokens of a name, without condition words."""
    return [part for part in tokens(text) if part not in VARIANT_WORDS]


def _same_identity(left: list[str], right: list[str]) -> bool:
    return Counter(left) == Counter(right)


def _key_variants(parts: list[str]) -> list[list[str]]:
    """The identity token lists a model name may stand for.

    A leading vendor brand or an instruction-tuned packaging word is a label,
    not a different model, so both sides may omit it.
    """
    keys = [list(parts)]
    if parts and parts[0] in VENDOR_WORDS:
        keys.append(list(parts[1:]))
    if parts and parts[-1] in ("it", "hf"):
        keys.append(list(parts[:-1]))
    return [key for key in keys if key]


def _target(model: str, options: Any) -> dict[str, Any]:
    forms, vendor, date = _id_forms(model)
    keys: list[list[str]] = []
    for form in forms:
        for key in _key_variants(_identity_tokens(form)):
            if key not in keys:
                keys.append(key)
    variant = native_variant(options)
    if not variant:
        trailing = tokens(str(model).split("/")[-1])
        variant = _variant_of_tokens(trailing) if trailing else ""
    return {
        "forms": forms,
        "vendor": vendor,
        "date": date,
        "keys": keys,
        "variant": variant,
    }


def _record_identities(record: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """The record's own identities: its slug and its display name.

    Both are published identities of the record. The display name keeps its
    release and capability annotations (``(Nov '24)``, ``(Vision)``); only a
    trailing reasoning marker is a measurement condition.
    """
    name = str(record.get("model") or "")
    slug = str(record.get("slug") or "")
    base, variant = variant_of(name)
    if not variant:
        variant = _variant_of_tokens(tokens(slug))
    identities: list[dict[str, Any]] = []
    for field, value in (("slug", slug), ("name", base)):
        parts = _identity_tokens(value)
        if parts:
            identities.append({"field": field, "tokens": parts})
    return identities, variant


def _dated_tokens(parts: list[str]) -> list[str]:
    return [part for part in parts if part.isdigit() and len(part) in (4, 8)]


def _matches(target: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Match one record, or return None.

    A checkpoint token is part of a record's slug or name, not part of the
    model identity, so the identity is compared with the token both kept and
    dropped. The token must still agree with the id: a short checkpoint must
    equal the id's checkpoint, and a release date must equal the record's
    ``release_date``.
    """
    identities, variant = _record_identities(record)
    refusal = ""
    for identity in identities:
        parts = identity["tokens"]
        variants = [(parts, "")]
        for token in dict.fromkeys(_dated_tokens(parts)):
            variants.append(([part for part in parts if part != token], token))
        for candidate, dropped in variants:
            if not any(
                _same_identity(key, wanted)
                for key in _key_variants(candidate)
                for wanted in target["keys"]
            ):
                continue
            if target["date"]:
                if len(target["date"]) == 10:
                    release = str(record.get("release_date") or "")
                    if release != target["date"]:
                        refusal = refusal or f"release date {release or 'unknown'} is not {target['date']}"
                        continue
                elif dropped != target["date"]:
                    refusal = refusal or f"checkpoint {target['date']} is not in the record"
                    continue
            elif dropped:
                # A dated record for an undated id: the checkpoint is
                # published with the binding, never hidden.
                pass
            return {
                "variant": variant,
                "id": str(record.get("id") or ""),
                "slug": str(record.get("slug") or ""),
                "name": str(record.get("model") or ""),
                "release_date": record.get("release_date"),
                "matched_by": identity["field"],
                "checkpoint": dropped,
                "record": dict(record),
            }
    if refusal:
        return {"refused": refusal}
    return None


def resolve(
    records: Iterable[Mapping[str, Any]],
    provider: str,
    model: str,
    *,
    options: Any = None,
) -> dict[str, Any]:
    """Resolve one model to its exact record, or say why it cannot be.

    The result always says what happened: `state` is measured, ambiguous or
    missing, and `reason` is a bounded code. A resolved record carries its id,
    slug, name, the variant it was measured under, the native variant and
    whether the two agree.
    """
    target = _target(model, options)
    if not target["keys"]:
        return {
            "state": "missing",
            "reason": "the model id carries no identity token",
            "record": None,
            "variant": target["variant"],
            "date": target["date"],
        }
    matches: list[dict[str, Any]] = []
    refusals: list[str] = []
    for record in records or ():
        if not isinstance(record, Mapping):
            continue
        found = _matches(target, record)
        if found is None:
            continue
        if "refused" in found:
            refusals.append(str(found["refused"]))
            continue
        matches.append(found)
    unique: dict[str, dict[str, Any]] = {}
    for match in matches:
        unique.setdefault(match["id"], match)
    matches = list(unique.values())
    if not matches:
        reason = refusals[0] if refusals else "no record with this identity"
        return {
            "state": "missing",
            "reason": reason,
            "record": None,
            "variant": target["variant"],
            "date": target["date"],
        }
    variants = sorted({match["variant"] for match in matches})
    chosen = None
    match_kind = ""
    if target["variant"]:
        chosen = next((match for match in matches if match["variant"] == target["variant"]), None)
        if chosen:
            match_kind = "exact"
    if chosen is None:
        chosen = next(
            (match for match in matches if not _variant_of_tokens(tokens(match["slug"]))),
            None,
        )
        if chosen:
            match_kind = "default" if not target["variant"] else "variant_mismatch"
    if chosen is None:
        if len(matches) == 1:
            chosen = matches[0]
            match_kind = "variant_mismatch"
        else:
            return {
                "state": "ambiguous",
                "reason": "several records for different variants: " + ", ".join(variants),
                "record": None,
                "variant": target["variant"],
                "date": target["date"],
                "variants": variants,
            }
    record = chosen
    checkpoint = record.get("checkpoint") or target["date"]
    return {
        "state": "measured",
        "reason": "",
        "record": dict(record.get("record") or {}),
        "id": record["id"],
        "slug": record["slug"],
        "name": record["name"],
        "release_date": record.get("release_date"),
        "measured_variant": record["variant"],
        "native_variant": target["variant"],
        "variant_match": match_kind,
        "variant_mismatch": match_kind == "variant_mismatch",
        "variants": variants,
        "date": target["date"],
        "matched_by": record.get("matched_by"),
        "checkpoint": checkpoint,
        "provenance": {
            "provider": provider,
            "model": model,
            "aa_id": record["id"],
            "aa_slug": record["slug"],
            "aa_name": record["name"],
            "release_date": record.get("release_date"),
            "measured_variant": record["variant"],
            "native_variant": target["variant"],
            "variant_match": match_kind,
            "matched_by": record.get("matched_by"),
            "checkpoint": checkpoint,
            "basis": (
                "the exact id, slug, name or documented alias of the model "
                "after removing routing, promotion and packaging wrappers"
            ),
        },
    }


def is_text_only(record: Mapping[str, Any] | None) -> bool:
    """True when the official evidence says the model takes text only."""
    if not isinstance(record, Mapping):
        return False
    slug = slugify(str(record.get("slug") or ""))
    name = str(record.get("model") or "").lower()
    return slug in TEXT_ONLY_EVIDENCE or name in TEXT_ONLY_EVIDENCE
