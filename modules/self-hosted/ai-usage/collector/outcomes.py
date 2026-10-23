"""The observed outcomes of the delegation rounds: the counts and the trust.

The ranking needs, per model and task type, the rounds that were observed
(the count n and the accepted count s) and the trust level of the model with
the reason it holds. This module reads them. Nothing calls it yet.

Three files are read, and none of them is written:

* the model identities (``model-identities.json``): the id of every model
  and the routes that serve it;
* the ledger: a SQLite database with a ``rounds`` table, opened read only;
* the backfill (``ghostship.delegation.backfill/v1``): the rounds the
  ledger does not carry, and the rounds whose verdict it corrects.

The identity of a route is decided in three steps, and the first one that
answers wins:

1. a route of an identity names this provider and this model;
2. the normalized model is the id of an identity, or the model of one of
   its routes;
3. the normalized model itself.

The normalization takes the last segment of a model id, folds its case and
strips a ``-free`` or ``:free`` suffix. A checkpoint tag such as
``:1017`` is kept, so a tagged model never pools with the untagged model
of the same name.

The trust of a model is the worse of two things: the level the owner's
runtime policy gives it (``model_trust.entries``), and the ledger's own
rule, that a model is not trusted again until three accepted rounds follow
its last fabrication. The order of the levels is the order of the ranking
(excluded, untrusted, backup, trusted), and it lives in the value policy.

Every reading is total: a file that is missing, unreadable or empty is an
empty history, and a model without a policy entry and without a
fabrication is trusted.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import catalog
from util import iso_to_epoch
from value_policy import TRUST_LEVELS, trust_rank

# The schema of the backfill file.
BACKFILL_SCHEMA = "ghostship.delegation.backfill/v1"

# The number of accepted rounds that follow a fabrication before the model
# is trusted again.
RECOVERY_ROUNDS = 3

# The verdicts that are a round of work, and the one that is a success.
# A round of the environment, an abandoned round and a round without a
# verdict are not rounds of work: they are counted by neither n nor s.
COUNTED_VERDICTS = ("accepted", "reworked", "rejected")
ACCEPTED_VERDICT = "accepted"

# The ledger's table and its columns. An older ledger has no verdict
# source, so the columns that are read are the ones the ledger carries.
LEDGER_TABLE = "rounds"
LEDGER_COLUMNS = (
    "model",
    "task_type",
    "verdict",
    "verdict_source",
    "cause",
    "fabrication",
    "started_at",
    "round_id",
)

# The fields of a backfill row.
BACKFILL_FIELDS = (
    "round_id",
    "model",
    "task_type",
    "started_at",
    "verdict",
    "fabrication",
    "ref",
    "summary",
)


# -- the model identities ------------------------------------------------


def load_identities(path: str | Path | None) -> list[dict[str, Any]]:
    """The model identities of the file, as a list of records.

    The file holds a ``models`` map, and every key of it is the id of a
    model, with the label and the routes that serve it::

        {"schema": "ghostship.model-identities/v1",
         "models": {"beam": {"label": "Beam",
                             "routes": ["ollama/beam"]}}}

    A file that is missing, unreadable or empty is no identity at all, and
    every route keeps its own model name.
    """
    if not path:
        return []
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return _identity_records(document)


def _identity_records(document: Any) -> list[dict[str, Any]]:
    """The identity records of a loaded document, in the order they are read.

    The file holds a ``models`` map, and the key of every entry of it is
    the id of the model. A list of records is read as it is, so the
    records of a loaded file can be read again without the file.
    """
    raw: list[Any] = []
    if isinstance(document, Mapping):
        models = document.get("models")
        if isinstance(models, Mapping):
            for key, value in models.items():
                if not isinstance(value, Mapping):
                    continue
                record = dict(value)
                record.setdefault("id", key)
                raw.append(record)
    elif isinstance(document, list):
        raw = list(document)

    records: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        identifier = str(entry.get("id") or entry.get("identity") or "").strip()
        if not identifier:
            continue
        routes = entry.get("routes")
        records.append(
            {
                "id": identifier,
                "label": str(entry.get("label") or ""),
                "model": str(entry.get("model") or ""),
                "routes": [
                    str(route) for route in routes if isinstance(route, str)
                ]
                if isinstance(routes, list)
                else [],
            }
        )
    return records


def _identity_list(identities: Any) -> list[dict[str, Any]]:
    """The identity records, from a list of them or from a whole document."""
    if identities is None:
        return []
    if isinstance(identities, (Mapping, list)):
        return _identity_records(identities)
    return []


def normalize_model(model: str) -> str:
    """The normalized name of a model.

    The name is the last segment of the id, folded, without a free
    suffix. A checkpoint tag is kept: ``deepseek-v4.1-flash:1017`` is not
    the model ``deepseek-v4.1-flash``.
    """
    text = str(model or "").strip()
    if "/" in text:
        text = text.rsplit("/", 1)[1]
    text = text.lower()
    changed = True
    while changed:
        changed = False
        for suffix in (":free", "-free"):
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                changed = True
                break
    return text


def _alias_provider(prefix: str) -> str | None:
    """The provider whose catalog an alias belongs to.

    An alias is a name of a provider's catalog: the collector's own
    provider names one, and the catalogs the provider falls back on are the
    others.
    """
    if prefix in catalog.PROVIDER_ALIASES:
        return prefix
    for provider, aliases in catalog.PROVIDER_ALIASES.items():
        if prefix in aliases:
            return provider
    return None


def identity_of(provider: str, model: str, identities: Any) -> str:
    """The identity of a route: the provider and the model it serves.

    The first step is the route of an identity: it names a provider of the
    route's own provider and the very model of the route. The second step
    is the normalized model, and the third is the normalized model itself.
    """
    records = _identity_list(identities)
    text = str(model or "")
    aliases = set(catalog.PROVIDER_ALIASES.get(provider, (provider,)))

    for record in records:
        for route in record["routes"]:
            prefix, separator, rest = route.partition("/")
            if not separator or prefix not in aliases:
                continue
            if rest.lower() != text.lower():
                continue
            return record["id"]

    normalized = normalize_model(text)
    if not normalized:
        return normalized
    for record in records:
        if record["id"].lower() == normalized:
            return record["id"]
    for record in records:
        if record["model"] and normalize_model(record["model"]) == normalized:
            return record["id"]
    for record in records:
        for route in record["routes"]:
            _, separator, rest = route.partition("/")
            if not separator:
                continue
            if normalize_model(rest) == normalized:
                return record["id"]
    return normalized


def identity_of_round(model_id: str, identities: Any) -> str:
    """The identity of a ledger round.

    A round names the provider of its model when it names one at all: the
    prefix of the model id is a catalog of a provider, and the round is
    that provider's round. A model id without such a prefix is the model
    itself.
    """
    text = str(model_id or "").strip()
    if "/" in text:
        prefix, _, rest = text.partition("/")
        provider = _alias_provider(prefix)
        if provider is not None:
            return identity_of(provider, rest, identities)
    return identity_of("", text, identities)


# -- the ledger -----------------------------------------------------------


def read_ledger(path: str | Path | None) -> list[dict[str, Any]]:
    """The rounds of the ledger, read only.

    The ledger is a SQLite database with a ``rounds`` table. It is opened
    read only: the collector never writes the ledger. A ledger that is
    missing, unreadable or carries no rounds table is an empty history,
    and not an error.
    """
    if not path:
        return []
    location = Path(path)
    try:
        uri = f"{location.resolve().as_uri()}?mode=ro"
    except OSError:
        return []
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.Error:
        return []
    try:
        connection.row_factory = sqlite3.Row
        columns = [
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({LEDGER_TABLE})")
        ]
        if not columns:
            return []
        selected = [name for name in LEDGER_COLUMNS if name in columns]
        rows = connection.execute(
            f"SELECT {', '.join(selected)} FROM {LEDGER_TABLE}"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    return [{name: row[name] for name in selected} for row in rows]


# -- the backfill ---------------------------------------------------------


def load_backfill(path: str | Path | None) -> list[dict[str, Any]]:
    """The rounds of the backfill file.

    The file carries the rounds the ledger does not have, and the rounds
    whose verdict the ledger got wrong::

        {"schema": "ghostship.delegation.backfill/v1",
         "rounds": [{"round_id": "r-7", "model": "ollama/beam",
                     "task_type": "research", "started_at": "2026-10-20T10:00:00Z",
                     "verdict": "accepted", "fabrication": 0, "ref": "chat-77",
                     "summary": "the review accepted the answer"}]}

    A file that is missing, unreadable, of another schema or without rounds
    is no round at all.
    """
    if not path:
        return []
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(document, Mapping):
        return []
    schema = document.get("schema")
    if schema is not None and str(schema) != BACKFILL_SCHEMA:
        return []
    rounds = document.get("rounds")
    if not isinstance(rounds, list):
        return []
    return [
        {name: row[name] for name in BACKFILL_FIELDS if name in row}
        for row in rounds
        if isinstance(row, Mapping)
    ]


# -- the rounds -----------------------------------------------------------


def _is_fabrication(value: Any) -> bool:
    """True when a round records a fabrication."""
    if value is None or isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "none")
    return bool(value)


def _time_value(value: Any) -> float | None:
    """The epoch of a timestamp, or None when it is not one."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return iso_to_epoch(text)
    return None


def _date_text(value: Any) -> str:
    """The text that names the date of a timestamp."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    epoch = _time_value(value)
    if epoch is None:
        return str(value)
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _order_key(value: Any) -> tuple[int, float, str]:
    """The key that orders two timestamps; an unknown time comes first."""
    epoch = _time_value(value)
    if epoch is None:
        return (0, 0.0, str(value or ""))
    return (1, epoch, "")


def _ledger_round(row: Mapping[str, Any]) -> dict[str, Any]:
    """One round of the ledger, in the shape the outcomes are read in."""
    identifier = str(row.get("round_id") or "")
    return {
        "round_id": identifier,
        "model": str(row.get("model") or ""),
        "task_type": str(row.get("task_type") or ""),
        "verdict": str(row.get("verdict") or "").strip().lower(),
        "verdict_source": str(row.get("verdict_source") or "").strip().lower(),
        "cause": str(row.get("cause") or ""),
        "fabrication": row.get("fabrication"),
        "started_at": row.get("started_at"),
        "ref": identifier or str(row.get("cause") or ""),
        "fabrication_ref": identifier or str(row.get("cause") or ""),
        "fabrication_source": "ledger",
    }


def _backfill_round(row: Mapping[str, Any]) -> dict[str, Any]:
    """One round of the backfill, in the shape the outcomes are read in."""
    identifier = str(row.get("round_id") or "")
    reference = str(row.get("ref") or "") or identifier
    return {
        "round_id": identifier,
        "model": str(row.get("model") or ""),
        "task_type": str(row.get("task_type") or ""),
        "verdict": str(row.get("verdict") or "").strip().lower(),
        "verdict_source": "backfill",
        "cause": str(row.get("summary") or ""),
        "fabrication": row.get("fabrication"),
        "started_at": row.get("started_at"),
        "ref": reference,
        "fabrication_ref": reference,
        "fabrication_source": "backfill",
    }


def _merged_rounds(
    rounds: Sequence[Mapping[str, Any]] | None,
    backfill: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """The rounds of the ledger with the backfill applied to them.

    A backfill row that names a round of the ledger replaces that round's
    verdict and its fabrication, unless the verdict of the ledger is a
    manual one: a manual verdict is the owner's, and it stands.

    A backfill row that names no round of the ledger is older history, and
    it counts only when it is older than the first round the ledger
    carries. A ledger that carries no round at all leaves every backfill
    row to count: there is nothing it could double count.
    """
    merged = [
        _ledger_round(row) for row in (rounds or ()) if isinstance(row, Mapping)
    ]
    by_id = {
        round_["round_id"]: round_ for round_ in merged if round_["round_id"]
    }

    first = None
    for round_ in merged:
        epoch = _time_value(round_.get("started_at"))
        if epoch is None:
            continue
        if first is None or epoch < first:
            first = epoch

    for row in backfill or ():
        if not isinstance(row, Mapping):
            continue
        record = _backfill_round(row)
        identifier = record["round_id"]
        if identifier and identifier in by_id:
            target = by_id[identifier]
            if target["verdict_source"] == "manual":
                # The manual verdict of the ledger is the owner's, and the
                # backfill does not overrule it.
                continue
            if "verdict" in row:
                target["verdict"] = record["verdict"]
            if "fabrication" in row:
                target["fabrication"] = record["fabrication"]
                target["fabrication_ref"] = record["fabrication_ref"]
                target["fabrication_source"] = record["fabrication_source"]
            continue
        # A row the ledger does not carry is older history.
        epoch = _time_value(record.get("started_at"))
        if first is not None and (epoch is None or epoch >= first):
            continue
        merged.append(record)
    return merged


def outcome_counts(
    rounds: Sequence[Mapping[str, Any]] | None,
    backfill: Sequence[Mapping[str, Any]] | None,
    identities: Any,
) -> dict[tuple[str, str], dict[str, Any]]:
    """The observed rounds of every model and task type.

    The count n is the rounds of work: an accepted round, a reworked round
    and a rejected round. The count s is the accepted rounds. A round of
    the environment, an abandoned round and a round without a verdict are
    not rounds of work, and they are counted by neither.

    The fabrications of the model are listed with the round they were seen
    on, so the trust of the model can name them.
    """
    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for round_ in _merged_rounds(rounds, backfill):
        identity = identity_of_round(round_["model"], identities)
        key = (identity, round_["task_type"])
        entry = counts.setdefault(key, {"n": 0, "s": 0, "fabrications": []})
        verdict = round_["verdict"]
        if verdict in COUNTED_VERDICTS:
            entry["n"] += 1
            if verdict == ACCEPTED_VERDICT:
                entry["s"] += 1
        if _is_fabrication(round_.get("fabrication")):
            entry["fabrications"].append(
                {
                    "date": _date_text(round_.get("started_at")),
                    "ref": str(round_.get("fabrication_ref") or ""),
                    "source": str(round_.get("fabrication_source") or "ledger"),
                }
            )
    return counts


# -- the trust ------------------------------------------------------------


def _trust_rank(level: str) -> int:
    """The rank of a trust level: the worst of the levels is the highest.

    The order of the levels is the order of the ranking, and it lives in
    the value policy, so the trust of a model and the value of a route
    cannot disagree about it.
    """
    return trust_rank(str(level or "").strip().lower())


def _policy_document(policy: Any) -> Mapping[str, Any] | None:
    """The runtime policy, as a document, from a document or from a path."""
    if isinstance(policy, Mapping):
        return policy
    if isinstance(policy, (str, Path)):
        try:
            document = json.loads(Path(policy).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(document, Mapping):
            return document
    return None


def _policy_trust(
    identity: str, task_type: str, policy: Any
) -> dict[str, Any] | None:
    """The trust the owner's policy gives a model, or None when it is silent."""
    document = _policy_document(policy)
    if document is None:
        return None
    trust = document.get("model_trust")
    if not isinstance(trust, Mapping):
        return None
    entries = trust.get("entries")
    if not isinstance(entries, list):
        return None

    name = str(identity or "").lower()
    task = str(task_type or "")
    worst: dict[str, Any] | None = None
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        model = str(entry.get("model") or "")
        if not model or model.lower() != name:
            continue
        task_types = entry.get("task_types")
        named = (
            [str(value) for value in task_types if isinstance(value, str)]
            if isinstance(task_types, list)
            else []
        )
        if "*" not in named and task not in named:
            continue
        level = str(entry.get("level") or "").strip().lower()
        if level not in TRUST_LEVELS:
            continue
        candidate = {
            "level": level,
            "reason": str(entry.get("reason") or "")
            or f"the owner's policy holds the model {level} for {task or 'every task type'}",
            "evidence": {
                "model": model,
                "level": level,
                "task_types": named,
                "detail": entry.get("evidence"),
            },
            "source": "policy",
        }
        if worst is None or _trust_rank(level) > _trust_rank(worst["level"]):
            worst = candidate
    return worst


def _ledger_trust(
    identity: str,
    task_type: str,
    rounds: Sequence[Mapping[str, Any]] | None,
    backfill: Sequence[Mapping[str, Any]] | None,
    identities: Any,
) -> dict[str, Any] | None:
    """The trust the ledger gives a model, or None when it is silent.

    The ledger does not trust a model again until three accepted rounds
    follow its last fabrication. The reason names the date of the
    fabrication and its reference, so the reader can find the round.
    """
    found = [
        round_
        for round_ in _merged_rounds(rounds, backfill)
        if identity_of_round(round_["model"], identities) == identity
        and round_["task_type"] == task_type
    ]
    fabrications = [
        round_ for round_ in found if _is_fabrication(round_.get("fabrication"))
    ]
    if not fabrications:
        return None

    latest = max(fabrications, key=lambda round_: _order_key(round_.get("started_at")))
    date = _date_text(latest.get("started_at"))
    reference = str(latest.get("fabrication_ref") or latest.get("round_id") or "")
    accepted = _accepted_after(found, latest)
    evidence = {
        "fabrication": {"date": date, "ref": reference},
        "accepted_after": accepted,
        "required": RECOVERY_ROUNDS,
    }
    if accepted < RECOVERY_ROUNDS:
        return {
            "level": "untrusted",
            "reason": (
                f"the fabrication of {date} ({reference}) is followed by "
                f"{accepted} accepted rounds, fewer than the {RECOVERY_ROUNDS} needed"
            ),
            "evidence": evidence,
            "source": "ledger",
        }
    return {
        "level": "trusted",
        "reason": (
            f"{accepted} accepted rounds follow the fabrication of {date} "
            f"({reference})"
        ),
        "evidence": evidence,
        "source": "ledger",
    }


def _accepted_after(
    found: Sequence[Mapping[str, Any]], latest: Mapping[str, Any]
) -> int:
    """The accepted rounds that follow the last fabrication."""
    boundary = _time_value(latest.get("started_at"))
    if boundary is None:
        # The order of the rounds is unknown, so no accepted round can be
        # said to follow the fabrication.
        return 0
    accepted = 0
    for round_ in found:
        if round_["verdict"] != ACCEPTED_VERDICT:
            continue
        moment = _time_value(round_.get("started_at"))
        if moment is None or moment <= boundary:
            continue
        accepted += 1
    return accepted


def trust_for(
    identity: str,
    task_type: str,
    policy: Any,
    rounds: Sequence[Mapping[str, Any]] | None,
    backfill: Sequence[Mapping[str, Any]] | None,
    identities: Any,
) -> dict[str, Any]:
    """The trust of a model for a task type, and the reason it holds.

    The trust is the worse of the level the owner's policy gives the model
    and the level the ledger's own rule gives it. A model that neither
    speaks about is trusted.
    """
    candidates = [
        entry
        for entry in (
            _policy_trust(identity, task_type, policy),
            _ledger_trust(identity, task_type, rounds, backfill, identities),
        )
        if entry is not None
    ]
    if not candidates:
        return {
            "level": "trusted",
            "reason": "no policy entry and no fabrication speak about the model",
            "evidence": {},
            "source": "default",
        }
    return max(candidates, key=lambda entry: _trust_rank(entry["level"]))
