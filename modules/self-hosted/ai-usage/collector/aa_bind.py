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

import value_policy

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
    """Ordered identity units.

    The order is significant: ``gpt-1.6-sol`` and ``gpt-6.1-sol`` are
    different models, and so are ``sol-6.1-gpt`` and ``gpt-6.1-sol``. A version
    written ``6.1`` and a version written ``6-1`` are the same version, so a
    dotted number is split into its digit runs; everything else keeps its
    place.
    """
    value = str(text or "").lower()
    value = re.sub(r"[^a-z0-9.]+", " ", value)
    units: list[str] = []
    for chunk in value.split():
        for piece in re.findall(r"[a-z]+|\d+(?:\.\d+)*", chunk):
            units.extend(part for part in piece.split(".") if part)
    return units


def identity(text: str) -> tuple[str, ...]:
    """The model identity, without the measurement condition words.

    The units keep their order. Two identities are the same only when they
    are the same sequence, or when one version group sits on the other side
    of one family word, which is the one naming difference the official
    sources publish (``claude-haiku-4-5`` and ``Claude 4.5 Haiku``).
    """
    return tuple(part for part in tokens(text) if part not in VARIANT_WORDS)


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
    """The display name of a record and its proven measurement annotation.

    Only a trailing parenthetical the feed uses for the condition counts: a
    literal ``Max`` in ``Qwen3.8 Max`` is the model's name, not an effort
    setting, and a token count or a slug suffix is not an annotation either.
    """
    text = str(name or "").strip()
    match = re.search(r"\(([^)]+)\)\s*$", text)
    if match:
        for part in match.group(1).split(","):
            key = part.strip().lower()
            if key in VARIANT_MARKERS:
                return text[: match.start()].strip(), VARIANT_MARKERS[key]
    return text, ""


def annotation_unknown(name: str) -> bool:
    """True when the record's trailing annotation is not a known condition.

    A parenthetical the feed uses for something else (a release, a capability)
    is not a measurement condition, so the record's condition is unknown. It
    must never be presented as the model's exact condition.
    """
    match = re.search(r"\(([^)]+)\)\s*$", str(name or "").strip())
    if not match:
        return False
    for part in match.group(1).split(","):
        if part.strip().lower() in VARIANT_MARKERS:
            return False
    return True


def default_condition(name: str) -> bool:
    """True when the feed itself says the measured condition is the default.

    Artificial Analysis writes ``(Max, Default Fallback)`` for a model it ran
    at the provider's default setting. That annotation is the feed's own
    statement about the provider's default, not an inference from a slug.
    """
    match = re.search(r"\(([^)]+)\)\s*$", str(name or "").strip())
    if not match:
        return False
    return any("default fallback" in part.strip().lower() for part in match.group(1).split(","))


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
        value = option.get("current_value", option.get("currentValue"))
        if name not in ("variant", "reasoningeffort", "effort", "thinking"):
            continue
        if isinstance(value, bool):
            # A thinking switch is the model's own published setting.
            if name == "thinking":
                return "reasoning" if value else "none"
            continue
        if isinstance(value, str):
            key = value.strip().lower()
            if key in VARIANT_MARKERS:
                return VARIANT_MARKERS[key]
            if key in VARIANT_MARKERS.values():
                return key
    return ""


def alignment_option(options: Any, variant: str) -> tuple[str, str] | None:
    """The native option that can be set to the measured condition.

    The key is the option id the model actually publishes, and the value is
    the spelling that option lists. An option with no descriptor, or a
    descriptor that does not list the condition, cannot be aligned, and
    nothing is invented under a guessed key.
    """
    wanted = str(variant or "").strip().lower()
    if not wanted or not isinstance(options, list):
        return None
    aliases = {wanted}
    for spelling, marker in VARIANT_MARKERS.items():
        if marker == wanted:
            aliases.add(spelling)
    for option in options:
        if not isinstance(option, Mapping):
            continue
        name = str(option.get("id") or "")
        if not name:
            continue
        values = (
            option.get("values")
            or option.get("allowed")
            or option.get("allowedValues")
            or option.get("choices")
            or option.get("enum")
            or option.get("options")
        )
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if isinstance(value, Mapping):
                value = value.get("id")
            if value is None:
                continue
            if str(value).strip().lower() in aliases:
                return name, str(value)
    return None


def can_align(options: Any, variant: str) -> bool:
    """True when the native options publish a value for the measured one."""
    return alignment_option(options, variant) is not None


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
                # A full date is a release marker, checked against the
                # record's release date.
                date = f"{token[:4]}-{token[4:6]}-{token[6:]}"
                raw = raw[: match.start()]
            # A short checkpoint (1017, 0309) is part of the model identity:
            # it stays in the units, so an undated id never matches it.
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
    """The ordered identity units of a name.

    A condition word is removed only where the source proves it is an
    annotation. ``Qwen3.8 Max`` is the model's literal name, so ``max`` stays
    in its identity; ``Claude Opus 4.5 (Non-reasoning)`` carries the word in a
    measurement annotation, and that annotation is removed before the
    comparison.
    """
    return list(tokens(text))


def _version_placement(left: list[str], right: list[str]) -> bool:
    """True when one version group sits beside one other family word.

    Only an adjacent version/family pair may change sides, and the version
    keeps its own digits and order. A reordered model name therefore never
    matches: ``sol-6.1-gpt`` needs two moves, and ``gpt-1.6-sol`` has a
    different version, so both stay unknown.
    """
    for start in range(len(left)):
        if not left[start].isdigit():
            continue
        end = start
        while end < len(left) and left[end].isdigit():
            end += 1
        block = left[start:end]
        if end < len(left) and len(left[end]) == 1 and left[end].isalpha():
            # A size label such as 70B or 30B travels with its number.
            block = block + [left[end]]
            end += 1
        if start > 0 and not left[start - 1].isdigit():
            swapped = left[: start - 1] + block + [left[start - 1]] + left[end:]
            if swapped == right:
                return True
        if end < len(left) and not left[end].isdigit():
            swapped = left[:start] + [left[end]] + block + left[end + 1 :]
            if swapped == right:
                return True
    return False


def _same_identity(left: list[str], right: list[str]) -> str:
    """The match kind of two ordered identities, or the empty string."""
    if list(left) == list(right):
        return "exact"
    if len(left) == len(right) and _version_placement(list(left), list(right)):
        return "version_placement"
    return ""


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
    # The native effort is only what the model's own options publish. An id
    # that ends in -max or -reasoning is a model name, not proof of an
    # effort setting.
    variant = native_variant(options)
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
    slug_units = tokens(slug)
    if variant:
        # The annotation proves the slug's trailing marker is the same
        # condition, so both identities drop it.
        marker = tokens(_marker_text(variant))
        if slug_units[-len(marker) :] == marker:
            slug_units = slug_units[: -len(marker)]
    identities: list[dict[str, Any]] = []
    for field, parts in (("slug", slug_units), ("name", tokens(base))):
        if parts:
            identities.append({"field": field, "tokens": parts})
    return identities, variant


def _dated_tokens(parts: list[str]) -> list[str]:
    return [part for part in parts if part.isdigit() and len(part) in (4, 8)]


def _without_checkpoint(parts: list[str]) -> list[str]:
    """The identity of a dated record without its trailing checkpoint.

    A short checkpoint (``1017``) or a full release date (``20250929``) is the
    last token of the record's identity. The owner's assume-latest rule lets an
    undated id bind to the newest dated record of its family; the checkpoint is
    what makes the record newer, so it is removed only for that comparison.
    """
    value = list(parts)
    while value and value[-1].isdigit() and len(value[-1]) in (4, 8):
        value.pop()
    return value


def _match_date(match: Mapping[str, Any]) -> tuple[str, int]:
    """The date a matching record carries, for the newest-record rule.

    A full release date is stronger evidence than a short checkpoint. Within
    one evidence kind the values sort lexically (ISO date) or numerically
    (``MMDD``), so the newest record of a family is stable.
    """
    record = match.get("record") or {}
    release = str(record.get("release_date") or "")
    if len(release) >= 10:
        return ("release", int(release[:10].replace("-", "")))
    identities, _variant = _record_identities(record)
    checkpoints = [
        int(token)
        for identity in identities
        for token in identity["tokens"]
        if token.isdigit() and len(token) in (4, 8)
    ]
    if checkpoints:
        return ("checkpoint", max(checkpoints))
    return ("", 0)


def _has_checkpoint(target: Mapping[str, Any]) -> bool:
    """True when the id itself names a checkpoint.

    A short checkpoint (``0929``) stays in the identity instead of becoming a
    release date, but it still makes the id dated: the assume-latest rule only
    applies to an id that names no date at all.
    """
    return any(
        key and key[-1].isdigit() and len(key[-1]) in (4, 8)
        for key in target.get("keys") or ()
    )


def _latest_applies(target: Mapping[str, Any]) -> bool:
    """True when an undated or alias id may take the newest dated record."""
    return not target["date"] and not _has_checkpoint(target)


def _matches(
    target: Mapping[str, Any], record: Mapping[str, Any], *, latest: bool = False
) -> dict[str, Any] | None:
    """Match one record, or return None.

    The identity is compared as an ordered sequence, and a record is only
    judged on its checkpoint or release date after its identity matched. A
    record that names a checkpoint the id does not name is a different
    record: an undated id never borrows a dated model, whatever the cache
    order.
    """
    identities, variant = _record_identities(record)
    marker = tokens(_marker_text(variant)) if variant else []
    for identity in identities:
        parts = identity["tokens"]
        if latest and _latest_applies(target):
            # The owner's assume-latest rule: an undated id compares with the
            # record's family, and the newest dated record of that family wins
            # after the match. A dated id never takes this path.
            parts = _without_checkpoint(parts)
            if not parts:
                continue
        for key in _key_variants(parts):
            for wanted in target["keys"]:
                wanted_variants = [wanted]
                if marker and wanted[-len(marker) :] == marker:
                    # The record's own annotation proves this trailing word is
                    # a condition, not part of the model identity.
                    wanted_variants.append(wanted[: -len(marker)])
                for candidate in wanted_variants:
                    kind = _same_identity(key, candidate)
                    if not kind:
                        continue
                    if target["date"] and len(target["date"]) == 10:
                        release = str(record.get("release_date") or "")
                        if release != target["date"]:
                            return {
                                "refused": f"release date {release or 'unknown'} is not {target['date']}"
                            }
                    return {
                        "variant": variant,
                        "default": default_condition(str(record.get("model") or "")),
                        "id": str(record.get("id") or ""),
                        "slug": str(record.get("slug") or ""),
                        "name": str(record.get("model") or ""),
                        "release_date": record.get("release_date"),
                        "matched_by": identity["field"],
                        "match_kind": kind,
                        "record": dict(record),
                    }
    return None


def _reference_value(record: Mapping[str, Any]) -> float | None:
    """The model-selection value of one measured record.

    Both the intelligence index and the measured cost per task are required;
    a record without either has no selection value. The weights and the
    transform come from the owner's policy, so there is one scorer.
    """
    indices = record.get("indices") or {}
    intelligence = indices.get("intelligence_index")
    cost = record.get("cost_per_task")
    if not isinstance(intelligence, (int, float)) or isinstance(intelligence, bool):
        return None
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        return None
    cost_value = float(cost)
    if not (cost_value >= 0.0) or not (cost_value == cost_value) or cost_value == float("inf"):
        return None
    efficiency, _evidence = value_policy.cost_transform(
        cost_value, (), value_policy.DEFAULT_COST_TRANSFORM
    )
    if efficiency is None:
        return None
    value, _missing = value_policy.combine(
        {"intelligence": float(intelligence) / 100.0, "cost_per_task": efficiency},
        value_policy.VALUE_WEIGHTS,
    )
    return None if value is None else round(value, 6)


def _condition_alternatives(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alternatives = []
    for match in matches:
        record = match.get("record") or {}
        alternatives.append(
            {
                "id": match.get("id"),
                "slug": match.get("slug"),
                "name": match.get("name"),
                "condition": match.get("variant") or "",
                "intelligence": (record.get("indices") or {}).get("intelligence_index"),
                "cost_per_task": record.get("cost_per_task"),
                "value": _reference_value(record),
            }
        )
    return sorted(alternatives, key=lambda entry: str(entry.get("id") or ""))


def resolve(
    records: Iterable[Mapping[str, Any]],
    provider: str,
    model: str,
    *,
    options: Any = None,
    mode: str = "condition",
    latest: bool = False,
    evidence: Any = None,
) -> dict[str, Any]:
    """Resolve one model to its exact record, or say why it cannot be.

    The result always says what happened: `state` is measured, ambiguous or
    missing, and `reason` is a bounded code. The choice is independent of the
    order of the records: several records of the same variant are ambiguous,
    never the first one.
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
        found = _matches(target, record, latest=latest)
        if found is None:
            continue
        if "refused" in found:
            refusals.append(str(found["refused"]))
            continue
        matches.append(found)
    unique: dict[str, dict[str, Any]] = {}
    for match in matches:
        unique.setdefault(match["id"], match)
    matches = [unique[key] for key in sorted(unique)]
    assumed: dict[str, Any] = {}
    if latest and _latest_applies(target) and matches:
        # The owner's assume-latest rule: an undated or alias id binds to the
        # newest dated record of its family. A dated id never reaches this
        # branch, and a family with only undated records keeps its exact match.
        dated = [match for match in matches if _match_date(match) != ("", 0)]
        if dated:
            newest = max(_match_date(match) for match in dated)
            matches = [match for match in matches
                       if _match_date(match) == ("", 0) or _match_date(match) == newest]
            chosen = max(dated, key=_match_date)
            assumed = {
                "assumed_latest": True,
                "assumed_record": {
                    "id": chosen.get("id"),
                    "slug": chosen.get("slug"),
                    "name": chosen.get("name"),
                    "release_date": chosen.get("release_date"),
                    "date": list(newest),
                },
                "assumption_basis": "assumed latest (owner rule)",
                "evidence": list(evidence or []),
            }
    if not matches:
        reason = refusals[0] if refusals else "no record with this identity"
        return {
            "state": "missing",
            "reason": reason,
            "record": None,
            "variant": target["variant"],
            "date": target["date"],
            **assumed,
        }
    variants = sorted({match["variant"] for match in matches})
    alternatives = _condition_alternatives(matches)
    if mode == "reference":
        # The AA record is selected independently of the native runtime
        # setting: the best measured 80/20 value with both inputs wins.
        by_condition: dict[str, list[dict[str, Any]]] = {}
        for match in matches:
            by_condition.setdefault(match["variant"], []).append(match)
        for condition, group in by_condition.items():
            if len({entry["id"] for entry in group}) > 1:
                return {
                    "state": "ambiguous",
                    "reason": "several records of the same measured condition: "
                    + ", ".join(sorted(entry["id"] for entry in group)),
                    "record": None,
                    "variant": "",
                    "date": target["date"],
                    "variants": variants,
                    "alternatives": alternatives,
                    **assumed,
                }
        valued = [
            (value, match)
            for match in matches
            for value in [_reference_value(match.get("record") or {})]
            if value is not None
        ]
        if valued:
            valued.sort(
                key=lambda item: (
                    -item[0],
                    -(float((item[1].get("record") or {}).get("indices", {}).get("intelligence_index") or 0.0)),
                    str(item[1]["id"]),
                )
            )
            value, chosen = valued[0]
            match_kind = "reference"
            record = chosen
            checkpoint = target["date"]
            return {
                "state": "measured",
                "reason": "",
                "record": dict(record.get("record") or {}),
                "id": record["id"],
                "slug": record["slug"],
                "name": record["name"],
                "release_date": record.get("release_date"),
                "measured_variant": record["variant"],
                "native_variant": "",
                "variant_match": match_kind,
                "variant_mismatch": False,
                "condition_confirmed": True,
                "condition_unknown": False,
                "variants": variants,
                "alternatives": alternatives,
                "reference": {
                    "value": value,
                    "condition": record["variant"],
                    "id": record["id"],
                    "basis": (
                        "the best measured 0.80 intelligence + 0.20 cost value "
                        "among the exact records of this model; independent of "
                        "the native runtime setting"
                    ),
                    "alternatives": alternatives,
                },
                "date": target["date"],
                "matched_by": record.get("matched_by"),
                "identity_match": record.get("match_kind"),
                "checkpoint": checkpoint,
                "provenance": {
                    "provider": provider,
                    "model": model,
                    "aa_id": record["id"],
                    "aa_slug": record["slug"],
                    "aa_name": record["name"],
                    "release_date": record.get("release_date"),
                    "measured_variant": record["variant"],
                    "native_variant": "",
                    "variant_match": match_kind,
                    "condition_confirmed": True,
                    "matched_by": record.get("matched_by"),
                    "identity_match": record.get("match_kind"),
                    "checkpoint": checkpoint,
                    "basis": "the model-selection reference, independent of the native setting",
                },
                **assumed,
            }
        # A record exists but no measured value can be computed: the identity
        # and conditions stay visible, and there is no selection reference.
        return {
            "state": "measured",
            "reason": "no measured value: both intelligence and cost per task are required",
            "record": dict(matches[0].get("record") or {}),
            "id": matches[0]["id"],
            "slug": matches[0]["slug"],
            "name": matches[0]["name"],
            "release_date": matches[0].get("release_date"),
            "measured_variant": matches[0]["variant"],
            "native_variant": "",
            "variant_match": "reference",
            "variant_mismatch": False,
            "condition_confirmed": True,
            "condition_unknown": False,
            "variants": variants,
            "alternatives": alternatives,
            "reference": None,
            "value_missing": [
                name
                for name in ("intelligence", "cost_per_task")
                if name
                == "cost_per_task"
                and not isinstance((matches[0].get("record") or {}).get("cost_per_task"), (int, float))
                or name == "intelligence"
                and not isinstance(
                    ((matches[0].get("record") or {}).get("indices") or {}).get("intelligence_index"),
                    (int, float),
                )
            ],
            "date": target["date"],
            "matched_by": matches[0].get("matched_by"),
            "identity_match": matches[0].get("match_kind"),
            "checkpoint": target["date"],
            "provenance": {"provider": provider, "model": model},
            **assumed,
        }
    chosen = None
    match_kind = ""
    if target["variant"]:
        exact = [match for match in matches if match["variant"] == target["variant"]]
        if len(exact) == 1:
            chosen = exact[0]
            match_kind = "exact"
        elif len(exact) > 1:
            return {
                "state": "ambiguous",
                "reason": "several records of the measured variant: "
                + ", ".join(sorted(match["id"] for match in exact)),
                "record": None,
                "variant": target["variant"],
                "date": target["date"],
                "variants": variants,
                **assumed,
            }
        elif len(matches) == 1:
            chosen = matches[0]
            match_kind = "variant_mismatch"
        else:
            return {
                "state": "ambiguous",
                "reason": "several records, none of the native variant: "
                + ", ".join(variants),
                "record": None,
                "variant": target["variant"],
                "date": target["date"],
                "variants": variants,
                **assumed,
            }
    elif len(matches) == 1:
        chosen = matches[0]
        # The id publishes no effort: the record's condition is displayed and
        # is not taken as proof that the model runs that way.
        match_kind = "unconfirmed" if chosen["variant"] else "exact"
    else:
        # Several measured conditions and no native effort. Only the feed's
        # own "Default Fallback" annotation may stand for the model's
        # condition; without it the condition is unknown.
        defaults = [match for match in matches if match.get("default")]
        if len(defaults) == 1:
            chosen = defaults[0]
            match_kind = "default"
        else:
            return {
                "state": "ambiguous",
                "reason": "several measured conditions and no published native variant: "
                + ", ".join(variants),
                "record": None,
                "variant": target["variant"],
                "date": target["date"],
                "variants": variants,
                **assumed,
            }
    record = chosen
    checkpoint = target["date"]
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
        "condition_confirmed": match_kind in ("exact", "default")
        and not annotation_unknown(record.get("name") or ""),
        "condition_unknown": annotation_unknown(record.get("name") or ""),
        "variants": variants,
        "date": target["date"],
        "matched_by": record.get("matched_by"),
        "identity_match": record.get("match_kind"),
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
            "condition_confirmed": match_kind in ("exact", "default")
            and not annotation_unknown(record.get("name") or ""),
            "condition_unknown": annotation_unknown(record.get("name") or ""),
            "matched_by": record.get("matched_by"),
            "identity_match": record.get("match_kind"),
            "checkpoint": checkpoint,
            "basis": (
                "the ordered id, slug, name or documented alias of the model "
                "after removing routing, promotion and packaging wrappers"
            ),
        },
        **assumed,
    }


def is_text_only(record: Mapping[str, Any] | None) -> bool:
    """True when the official evidence says the model takes text only."""
    if not isinstance(record, Mapping):
        return False
    slug = slugify(str(record.get("slug") or ""))
    name = str(record.get("model") or "").lower()
    return slug in TEXT_ONLY_EVIDENCE or name in TEXT_ONLY_EVIDENCE
