"""The Artificial Analysis public pull: no key, no account, no paywall.

The leaderboard page, the model pages and the AA-3D page are public. This
module reads them with ordinary GETs, parses the pages, and writes the
cache the collector reads.

The rules are narrow on purpose:

* only GETs, only public pages, and no credential of any kind;
* a page that is blocked, that answers with a challenge, or that is not
  there is recorded as blocked, and the last good snapshot is kept: nothing
  is retried to get around anything;
* a deprecated model is still a model. It is published with
  ``deprecated: true``, because deprecated means superseded, not
  unavailable;
* a cost per task that the page itself publishes is used as it is
  published, with the basis ``aa_model_page``. A cost is never estimated:
  an estimate is not a measurement, and the value formula needs a
  measurement.

The pull reads the AA-3D page first and writes its snapshot as soon as
the page is parsed, so a model page that is slow, that times out or that
fails cannot lose it. The model pages are then read under a total budget:
a page is started only while enough of the budget is left for it to
finish, the pages that are not read are counted, and the quality cache
is written either way.

The pull runs at most once a day. The collector itself never calls the
network: it reads the cache the pull wrote.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import aa
import aa_diff

# The AA-3D page. It is read first: its snapshot is written as soon as
# the page is parsed, so a model page that is slow cannot lose it.
AA3D_URL = "https://artificialanalysis.ai/evaluations/aa-3d"

# The public pages the pull reads.
SOURCES = (
    (
        "leaderboard",
        "https://artificialanalysis.ai/leaderboards/models",
        "primary: the scored model rows with the intelligence index and the "
        "published cost per task",
    ),
    (
        "models",
        "https://artificialanalysis.ai/models",
        "release dates, creators, the model variants and the detailed models",
    ),
    (
        "aa3d",
        AA3D_URL,
        "the AA-3D Elo and its interval",
    ),
)

# The marker of a bot-protection or challenge page. A page that carries one
# is not read. It is recorded as blocked, and the last good snapshot is
# kept.
CHALLENGE_MARKERS = (
    "captcha",
    "cf-browser-verification",
    "cf_chl_opt",
    "just a moment",
    "checking your browser",
    "px-captcha",
    "challenge-platform",
)

# The user agent of an ordinary browser read.
USER_AGENT = aa.USER_AGENT

# The largest page the reader accepts. A larger answer is refused rather
# than buffered.
MAX_BYTES = aa.MAX_BYTES

# The timeout of one read.
TIMEOUT_SECONDS = aa.TIMEOUT_SECONDS

# The cost basis of a cost the model page publishes.
COST_BASIS_PUBLISHED = "aa_leaderboard"
COST_BASIS_MODEL_PAGE = "aa_model_page"

# A model page is about four megabytes. The pull reads only the pages of the
# models the live catalog still offers, and it reads at most this many of
# them in one run. The count is reported with the result.
MAX_MODEL_PAGE_FETCHES = 10

# The budget of one pull, in seconds. The pull reads public pages over the
# network, and a page that is slow must not let the run outlive the unit
# that runs it. The budget is measured from the moment the AA-3D snapshot
# has been written, that is, from the start of the part of the pull that
# reads the model pages, and it stays well below the timeout of that unit.
PULL_BUDGET_SECONDS = 480.0

# A model page is started only while this much of the budget is left, so a
# page that is read at the last moment still has the time to finish.
MIN_REMAINING_SECONDS = 90.0

# The clock the budget of the model pages is measured with. A test moves it
# by hand: the pull reads pages over the network, and a slow page has to be
# a number and not a minute of waiting.
CLOCK: Any = time.monotonic

# A deprecated model is superseded, not changed: its published cost is read
# once and never again. A model that is not deprecated but is absent from
# the leaderboard may still change, so it is read again - but not more than
# once a week.
MODEL_PAGE_REFETCH_SECONDS = 7 * 24 * 3600.0


def _normalise(name: str) -> str:
    """The name without its separators, so a page and a catalog agree."""
    return "".join(
        character for character in str(name or "").lower() if character.isalnum()
    )

# The markers of a page that publishes its cost per task in its text.
_COST_IN_TEXT = re.compile(
    r"it costs \$([0-9]+(?:\.[0-9]+)?) per task to evaluate ([^<]+?) on the "
    r"Intelligence Index"
)

# The Next.js flight chunk of a page.
_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def _fetch(url: str) -> dict[str, Any]:
    """Read one public page, or say why it could not be read.

    A page that is blocked, that answers with a challenge, or that is not
    there is recorded as blocked. There is no retry: the pull is a read of
    public pages, and a refused read stays refused.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200) or 200
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        return {
            "url": url,
            "http_status": int(error.code),
            "bytes": 0,
            "blocked": True,
            "error": f"HTTP {error.code}",
        }
    except (urllib.error.URLError, OSError, ValueError) as error:
        return {
            "url": url,
            "http_status": None,
            "bytes": 0,
            "blocked": True,
            "error": type(error).__name__,
        }
    if len(body) > MAX_BYTES:
        return {
            "url": url,
            "http_status": int(status),
            "bytes": len(body),
            "blocked": True,
            "error": "the page is larger than the reader accepts",
        }
    text = body.decode("utf-8", errors="replace")
    lowered = text[:200000].lower()
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        return {
            "url": url,
            "http_status": int(status),
            "bytes": len(body),
            "blocked": True,
            "error": "the page answered with a challenge",
        }
    return {
        "url": url,
        "http_status": int(status),
        "bytes": len(body),
        "blocked": False,
        "error": None,
        "text": text,
    }


def _flight_buffer(html: str) -> str:
    """Concatenate the page's flight chunks into one string."""
    chunks = _FLIGHT.findall(html or "")
    parts: list[str] = []
    for chunk in chunks:
        try:
            parts.append(json.loads(chunk))
        except ValueError:
            continue
    return "".join(parts)


def _json_array_after(buffer: str, key: str) -> Any:
    """The JSON array that follows the first occurrence of `"key":[`."""
    index = buffer.find(f'"{key}":[')
    if index < 0:
        return None
    start = buffer.index("[", index)
    try:
        array, _offset = json.JSONDecoder().raw_decode(buffer[start:])
    except ValueError:
        return None
    return array


def _objects_in(buffer: str) -> list[list[Mapping[str, Any]]]:
    """Every array of objects the page carries, biggest first."""
    decoder = json.JSONDecoder()
    found: list[list[Mapping[str, Any]]] = []
    for match in re.finditer(r"\[\{", buffer):
        try:
            array, _offset = decoder.raw_decode(buffer[match.start():])
        except ValueError:
            continue
        if isinstance(array, list) and array and isinstance(array[0], Mapping):
            found.append(array)
    return found


def _aa3d_table(html: str) -> dict[str, dict[str, Any]]:
    """The rendered AA-3D leaderboard: the Elo and its interval."""
    rows: dict[str, dict[str, Any]] = {}
    for match in re.finditer(r"<tr\b", html or ""):
        end = html.find("</tr>", match.start())
        if end < 0:
            continue
        row = html[match.start():end]
        name = re.search(r'class="font-medium min-w-0 truncate"[^>]*>([^<]+)<', row)
        elo = re.search(r'class="w-10 text-right">(\d+)<', row)
        interval = re.search(r"95% interval (\d+) to (\d+)", row)
        if not (name and elo):
            continue
        rows[name.group(1).strip()] = {
            "elo_display": int(elo.group(1)),
            "ci95_lower": int(interval.group(1)) if interval else None,
            "ci95_upper": int(interval.group(2)) if interval else None,
        }
    return rows


def _cost_in_text(text: str) -> float | None:
    """The cost per task a page publishes in its own text."""
    match = _COST_IN_TEXT.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _reasoning_condition(name: str, release_name: str) -> str | None:
    """The reasoning condition a display name carries."""
    if not release_name:
        return None
    display = str(name or "").strip()
    release = str(release_name).strip()
    if display == release:
        return None
    if display.startswith(release):
        rest = display[len(release):].strip().strip("()").strip()
        return rest or None
    match = re.search(r"\(([^()]*)\)\s*$", display)
    if match:
        return match.group(1).strip()
    return None


def _record(
    slug: str,
    name: str,
    *,
    creator: str = "",
    intelligence: Any = None,
    estimated: bool = False,
    cost_per_task: Any = None,
    cost_basis: str = "",
    price_input: Any = None,
    price_output: Any = None,
    cache_hit: Any = None,
    cache_write: Any = None,
    speed: Any = None,
    release_date: Any = None,
    reasoning: Any = None,
    deprecated: bool = False,
    elo: Any = None,
) -> dict[str, Any]:
    """One record in the cache contract."""
    record: dict[str, Any] = {
        "model": name,
        "slug": slug,
        "id": f"aa-{slug}",
        "provider": creator,
        "release_date": release_date if isinstance(release_date, str) else None,
        "indices": {
            "intelligence_index": _number(intelligence),
            "coding_index": None,
            "agentic_index": None,
            "engineering_index": None,
        },
        "prices": {
            "input": _number(price_input),
            "output": _number(price_output),
            "cache_read": _number(cache_hit),
            "cache_write": _number(cache_write),
        },
        "cost_per_task": _number(cost_per_task),
        "median_performance": _number(speed),
        "median_time_to_first_token_seconds": None,
        "deprecated": bool(deprecated),
        "reasoning_condition": reasoning,
        "cost_basis": cost_basis,
        "aa3d_elo": _number(elo),
    }
    record["intelligence_index_is_estimated"] = bool(estimated)
    return record


def _number(value: Any) -> float | None:
    """A finite float, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def parse_leaderboard(html: str) -> dict[str, dict[str, Any]]:
    """The scored model rows of the leaderboard page."""
    buffer = _flight_buffer(html)
    rows = _json_array_after(buffer, "initialModels")
    found: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        found[slug] = {
            "name": str(row.get("name") or slug),
            "creator": str(row.get("modelCreatorName") or ""),
            "intelligence": row.get("intelligenceIndex"),
            "estimated": bool(row.get("intelligenceIndexIsEstimated")),
            "cost_per_task": row.get("intelligenceIndexCostPerTask"),
            "price_input": row.get("price1mInputTokens"),
            "price_output": row.get("price1mOutputTokens"),
            "cache_hit": row.get("cacheHitPrice"),
            "cache_write": row.get("cacheWritePrice"),
            "speed": row.get("medianOutputTokensPerSecond"),
            "release_date": row.get("releaseDate"),
            "deprecated": bool(row.get("deprecated")),
            "elo": row.get("aa3dElo"),
        }
    return found


def parse_model_page(html: str) -> dict[str, Any]:
    """The model of a model page.

    A model page carries the whole model, including the deprecated ones the
    leaderboard omits. The page is one model, so the record is read as one
    object and never as a window of a text page.
    """
    buffer = _flight_buffer(html)
    index = buffer.find('"currentModel":{')
    if index < 0:
        return {}
    try:
        record, _offset = json.JSONDecoder().raw_decode(
            buffer[index + len('"currentModel":'):]
        )
    except ValueError:
        return {}
    if not isinstance(record, Mapping):
        return {}
    release = record.get("release") if isinstance(record.get("release"), Mapping) else {}
    creator = record.get("creator") if isinstance(record.get("creator"), Mapping) else {}
    cost = record.get("intelligenceIndexCostPerTask")
    cost_per_task = None
    if isinstance(cost, Mapping) and isinstance(cost.get("cost"), Mapping):
        cost_per_task = cost["cost"].get("total")
    return {
        "slug": str(record.get("slug") or ""),
        "name": str(record.get("name") or ""),
        "creator": str(creator.get("name") or ""),
        "intelligence": record.get("intelligenceIndex"),
        "estimated": bool(record.get("intelligenceIndexIsEstimated")),
        "cost_per_task": cost_per_task,
        "price_input": record.get("price1mInputTokens"),
        "price_output": record.get("price1mOutputTokens"),
        "cache_hit": record.get("cacheHitPrice"),
        "cache_write": record.get("cacheWritePrice"),
        "speed": record.get("medianCanonicalAnswerOutputSpeed"),
        "release_date": record.get("releaseDate"),
        "deprecated": bool(record.get("deprecated")),
        "reasoning": record.get("suffix"),
        "deprecated_to": str(release.get("deprecatedTo") or ""),
        "elo": record.get("aa3dElo"),
    }


def parse_models(html: str) -> dict[str, dict[str, Any]]:
    """The releases, the variants and the detailed models of the models page."""
    buffer = _flight_buffer(html)
    releases: list[Mapping[str, Any]] = []
    variants: list[Mapping[str, Any]] = []
    detailed: list[Mapping[str, Any]] = []
    for array in _objects_in(buffer):
        keys = set(array[0].keys())
        if {"slug", "name", "releaseSlug"} <= keys and len(array) > len(variants):
            variants = array
        if {"slug", "name", "releaseDate", "creator"} <= keys and len(array) > len(releases):
            releases = array
        if {"slug", "suffix", "creator", "releaseDate", "intelligenceIndexCost"} <= keys:
            detailed = array
            break
    release_by_slug = {
        str(row.get("slug")): row
        for row in releases
        if isinstance(row, Mapping) and row.get("slug")
    }
    variant_by_slug = {
        str(row.get("slug")): row
        for row in variants
        if isinstance(row, Mapping) and row.get("slug")
    }
    found: dict[str, dict[str, Any]] = {}
    for row in detailed:
        if not isinstance(row, Mapping):
            continue
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        cost = row.get("intelligenceIndexCostPerTask")
        cost_per_task = None
        if isinstance(cost, Mapping) and isinstance(cost.get("cost"), Mapping):
            cost_per_task = cost["cost"].get("total")
        release = row.get("release") if isinstance(row.get("release"), Mapping) else {}
        creator = row.get("creator") if isinstance(row.get("creator"), Mapping) else {}
        found[slug] = {
            "name": str(row.get("name") or slug),
            "creator": str(creator.get("name") or ""),
            "intelligence": row.get("intelligenceIndex"),
            "estimated": bool(row.get("intelligenceIndexIsEstimated")),
            "cost_per_task": cost_per_task,
            "price_input": row.get("price1mInputTokens"),
            "price_output": row.get("price1mOutputTokens"),
            "cache_hit": row.get("cacheHitPrice"),
            "cache_write": row.get("cacheWritePrice"),
            "speed": row.get("medianCanonicalAnswerOutputSpeed"),
            "release_date": row.get("releaseDate"),
            "deprecated": bool(row.get("deprecated")),
            "reasoning": row.get("suffix"),
            "deprecated_to": str(release.get("deprecatedTo") or ""),
            "elo": row.get("aa3dElo"),
        }
    # The variants carry the release date and the creator of their release.
    for slug, variant in variant_by_slug.items():
        release = release_by_slug.get(str(variant.get("releaseSlug")))
        entry = found.get(slug)
        if entry is None:
            continue
        if entry.get("release_date") is None and release is not None:
            entry["release_date"] = release.get("releaseDate")
        if not entry.get("creator") and release is not None:
            creator = release.get("creator")
            if isinstance(creator, Mapping):
                entry["creator"] = str(creator.get("name") or "")
        if entry.get("reasoning") is None:
            entry["reasoning"] = _reasoning_condition(
                str(variant.get("name") or entry["name"]),
                str((release or {}).get("name") or ""),
            )
    return found


def parse_aa3d(html: str) -> dict[str, dict[str, Any]]:
    """The AA-3D board: the Elo of every model it shows."""
    buffer = _flight_buffer(html)
    rows = _json_array_after(buffer, "initialModels")
    table = _aa3d_table(html)
    found: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        name = str(row.get("name") or slug)
        entry = {
            "elo": row.get("aa3dElo"),
            "name": name,
            "creator": str((row.get("creator") or {}).get("name") or "")
            if isinstance(row.get("creator"), Mapping)
            else "",
            "release_date": row.get("releaseDate"),
            "reasoning": row.get("suffix"),
        }
        rendered = table.get(name)
        if rendered:
            entry["elo_display"] = rendered.get("elo_display")
            entry["ci95_lower"] = rendered.get("ci95_lower")
            entry["ci95_upper"] = rendered.get("ci95_upper")
        found[slug] = entry
    return found


class _ModelPageBudget:
    """The time one pull may spend on the model pages.

    The pull has a total budget, and a model page is started only while
    enough of it is left for the page to finish. The pages that are not
    read are counted, so a run that skipped them says so.

    The clock is injected: a test reads the pages of a fixture and moves
    the clock by hand, with no network and no sleeping.
    """

    def __init__(
        self,
        clock: Any,
        *,
        budget_seconds: float = PULL_BUDGET_SECONDS,
        min_remaining: float = MIN_REMAINING_SECONDS,
    ) -> None:
        self._clock = clock
        self._budget = float(budget_seconds)
        self._min_remaining = float(min_remaining)
        self.started = float(clock())
        self.skipped = 0

    def used(self) -> float:
        """The seconds of the budget the pull has spent."""
        return float(self._clock()) - self.started

    def remaining(self) -> float:
        """The seconds of the budget that are left."""
        return self._budget - self.used()

    def allow(self) -> bool:
        """True when a model page may be started now."""
        return self.remaining() >= self._min_remaining


def _read_model_pages(
    records: dict[str, dict[str, Any]],
    leaderboard: Mapping[str, Any],
    *,
    model_pages: Any = None,
    offered: Iterable[str] = (),
    known: Mapping[str, Any] | None = None,
    now: float | None = None,
    budget: _ModelPageBudget | None = None,
) -> tuple[dict[str, Any], int]:
    """The published cost of the models whose page has to be read.

    A model page is about four megabytes, so the page is read only for a
    model the live catalog still offers, only when its cost is not known
    already, and at most this many times in one run. The cost of a
    deprecated model never changes, so it is read once and never again; a
    model that is not deprecated is read again at most once a week.

    With a budget, a page is read only while enough of the budget is left
    for it to finish. The pages that are not read are counted, and their
    models keep the cost they had: a cost that was not read is unknown,
    never zero.

    The result is the cost of every model whose page was read or whose
    cost was already known, and the number of pages that were read.
    """
    moment = time.time() if now is None else float(now)
    catalogue = {_normalise(slug) for slug in offered or () if str(slug)}
    cached = dict(known or {})
    costs: dict[str, Any] = {}
    fetches = 0
    for slug, entry in sorted(records.items()):
        if entry.get("cost_per_task") is not None:
            continue
        if not entry.get("deprecated") and slug in leaderboard:
            continue
        if catalogue and _normalise(slug) not in catalogue:
            # Nobody uses this model: its page is not worth a read.
            continue
        previous = cached.get(slug)
        if isinstance(previous, Mapping):
            cost = _number(previous.get("cost"))
            fetched_at = _number(previous.get("fetched_at"))
            deprecated = bool(previous.get("deprecated"))
            if cost is not None and (
                deprecated
                or (
                    fetched_at is not None
                    and (moment - fetched_at) < MODEL_PAGE_REFETCH_SECONDS
                )
            ):
                entry["cost_per_task"] = cost
                entry["cost_basis"] = COST_BASIS_MODEL_PAGE
                costs[slug] = dict(previous)
                continue
        if model_pages is None:
            continue
        if fetches >= MAX_MODEL_PAGE_FETCHES:
            # The cap of the run. The page is not read, and it is counted.
            if budget is not None:
                budget.skipped += 1
            continue
        if budget is not None and not budget.allow():
            # Not enough of the budget is left for a page to finish.
            budget.skipped += 1
            continue
        fetches += 1
        page = model_pages(slug)
        if not page:
            continue
        text = str(page.get("text") or "")
        model = parse_model_page(text) if text else {}
        if model.get("slug") and not entry.get("deprecated"):
            # The page carries a model the leaderboard did not list.
            entry["deprecated"] = bool(model.get("deprecated"))
            if entry.get("indices", {}).get("intelligence_index") is None:
                entry["indices"]["intelligence_index"] = _number(
                    model.get("intelligence")
                )
        cost = _cost_in_text(text)
        if cost is None:
            continue
        entry["cost_per_task"] = cost
        entry["cost_basis"] = COST_BASIS_MODEL_PAGE
        costs[slug] = {
            "cost": cost,
            "fetched_at": moment,
            "deprecated": bool(entry.get("deprecated")),
        }
    return costs, fetches


def pull(
    *,
    read: Any = None,
    model_pages: Any = None,
    catalog_slugs: Iterable[str] = (),
    cached_costs: Mapping[str, Any] | None = None,
    write_aa3d: Any = None,
) -> dict[str, Any]:
    """Pull the public pages and build the cache document.

    `read` is the function that reads one url and returns the reading of
    the pull module; `model_pages` reads the model page of a model that
    the leaderboard does not carry. Both are injectable, so a test can read
    a fixture without a network.

    `catalog_slugs` are the models the live catalog still offers, and only
    those have their model page read: a page is four megabytes, and a
    model nobody uses is not worth a read. `cached_costs` are the model
    page costs of an earlier pull, and a model whose cost is known is not
    read again.

    `write_aa3d` is called with the AA-3D board as soon as the AA-3D page
    has been read and parsed, before any model page is read. The AA-3D
    page is read first for that reason: a model page that is slow, that
    times out or that fails cannot lose the board.
    """
    offered = {_normalise(slug) for slug in catalog_slugs or () if str(slug)}
    known = dict(cached_costs or {})
    reader = read or _fetch
    entries: dict[str, dict[str, Any]] = {}
    pages: dict[str, str] = {}

    def read_source(key: str, url: str, role: str) -> str:
        """Read one public page, and record how the read went."""
        reading = reader(url)
        entries[key] = {
            "key": key,
            "url": url,
            "role": role,
            "http_status": reading.get("http_status"),
            "bytes": reading.get("bytes"),
            "blocked": bool(reading.get("blocked")),
            "error": reading.get("error"),
        }
        if reading.get("blocked"):
            return ""
        pages[key] = str(reading.get("text") or "")
        return pages[key]

    # The AA-3D page is read first, and its snapshot is written as soon as
    # the page is parsed. The 3D tier reads that file and not the cache,
    # so the board must not wait for the model pages.
    aa3d_role = next(role for key, _url, role in SOURCES if key == "aa3d")
    aa3d_html = read_source("aa3d", AA3D_URL, aa3d_role)
    board = parse_aa3d(aa3d_html)
    board_document = aa3d_document(board, time.time()) if board else {}
    if board_document.get("records") and write_aa3d is not None:
        write_aa3d(board_document)
    # The budget of the model pages starts here: the AA-3D snapshot has
    # been written, and the rest of the pull is what the budget pays for.
    budget = _ModelPageBudget(CLOCK)

    for key, url, role in SOURCES:
        if key == "aa3d":
            continue
        read_source(key, url, role)

    sources = [entries[key] for key, _url, _role in SOURCES]
    leaderboard = parse_leaderboard(pages.get("leaderboard") or "")
    models = parse_models(pages.get("models") or "")

    records: dict[str, dict[str, Any]] = {}
    for slug, entry in leaderboard.items():
        records[slug] = _record(
            slug,
            entry["name"],
            creator=entry["creator"],
            intelligence=entry["intelligence"],
            estimated=entry["estimated"],
            cost_per_task=entry["cost_per_task"],
            cost_basis=COST_BASIS_PUBLISHED,
            price_input=entry["price_input"],
            price_output=entry["price_output"],
            cache_hit=entry["cache_hit"],
            cache_write=entry["cache_write"],
            speed=entry["speed"],
            release_date=entry["release_date"],
            deprecated=entry["deprecated"],
            elo=entry.get("elo"),
        )
    for slug, entry in models.items():
        if slug in records:
            existing = records[slug]
            if existing.get("cost_per_task") is None and entry.get("cost_per_task") is not None:
                existing["cost_per_task"] = entry["cost_per_task"]
                existing["cost_basis"] = COST_BASIS_PUBLISHED
            for field, target in (
                ("release_date", "release_date"),
                ("reasoning", "reasoning"),
            ):
                if existing.get(target) is None and entry.get(field) is not None:
                    existing[target] = entry[field]
            if not existing.get("provider") and entry.get("creator"):
                existing["provider"] = entry["creator"]
            if existing.get("aa3d_elo") is None and entry.get("elo") is not None:
                existing["aa3d_elo"] = entry["elo"]
            continue
        # A model the leaderboard does not carry. It is still a model, and
        # it is published with its own deprecated flag.
        records[slug] = _record(
            slug,
            entry["name"],
            creator=entry["creator"],
            intelligence=entry["intelligence"],
            estimated=entry["estimated"],
            cost_per_task=entry["cost_per_task"],
            cost_basis=COST_BASIS_PUBLISHED,
            price_input=entry["price_input"],
            price_output=entry["price_output"],
            cache_hit=entry["cache_hit"],
            cache_write=entry["cache_write"],
            speed=entry["speed"],
            release_date=entry["release_date"],
            reasoning=entry["reasoning"],
            deprecated=entry["deprecated"],
            elo=entry.get("elo"),
        )
    # The AA-3D board fills the Elo of the models it shows.
    for slug, entry in board.items():
        record = records.get(slug)
        if record is None:
            record = _record(
                slug,
                entry["name"],
                creator=entry.get("creator") or "",
                release_date=entry.get("release_date"),
                reasoning=entry.get("reasoning"),
            )
            records[slug] = record
        if record.get("aa3d_elo") is None and entry.get("elo") is not None:
            record["aa3d_elo"] = entry["elo"]
        if record.get("aa3d_elo_interval") is None and entry.get("ci95_lower") is not None:
            record["aa3d_elo_interval"] = {
                "low": entry.get("ci95_lower"),
                "high": entry.get("ci95_upper"),
            }
    # A deprecated or leaderboard-absent model: its own page publishes the
    # cost per task. The page is read only for a model the live catalog
    # still offers, only when its cost is not known already, at most this
    # many times in one run, and only while the budget of the run has
    # enough left for the page to finish. The published number is used as
    # it is published, and a cost is never estimated.
    model_page_costs, fetches = _read_model_pages(
        records,
        leaderboard,
        model_pages=model_pages,
        offered=offered,
        known=known,
        budget=budget,
    )
    ordered = [records[slug] for slug in sorted(records)]
    fetched_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    )
    return {
        "status": "ok",
        "reason": "",
        "intelligence_index_version": aa.INTELLIGENCE_INDEX_VERSION,
        "tier": "public",
        "fetched_at": fetched_at,
        "fetched_at_epoch": time.time(),
        "source": "artificialanalysis_public_pages",
        "attribution": "Artificial Analysis (https://artificialanalysis.ai/)",
        "sources": sources,
        "blocked": [entry["url"] for entry in sources if entry["blocked"]],
        # The pages the quality records come from. The AA-3D page is not one
        # of them: a board that could not be read does not hold the quality
        # cache back, and the last good board is kept.
        "quality_blocked": [
            entry["url"]
            for entry in sources
            if entry["blocked"] and entry["key"] != "aa3d"
        ],
        "completeness": {
            "scope": "the public pages",
            "complete": not any(
                entry["blocked"] and entry["key"] != "aa3d" for entry in sources
            ),
            "pages_fetched": len(pages),
            "total_pages": len(SOURCES),
            "records": len(ordered),
        },
        "records": ordered,
        # The model page costs of this pull, and the models that were read.
        "model_page_costs": model_page_costs,
        "model_page_fetches": fetches,
        # The model pages that were not read, and the budget of the run.
        "model_page_skipped": budget.skipped,
        "model_page_budget_seconds": PULL_BUDGET_SECONDS,
        "model_page_budget_used_seconds": round(budget.used(), 3),
        # The AA-3D board, in the contract the collector reads it in.
        "aa3d": board_document,
    }


def aa3d_document(board: Mapping[str, Any], now: float) -> dict[str, Any]:
    """The AA-3D board, in the cache contract the collector reads.

    The board is the measured Elo of every model the page shows, with its
    interval. The ranks are the order of the board, and the normalization
    is the reader's own: the min-max over the complete board.
    """
    import aa_3d

    entries: list[dict[str, Any]] = []
    ranked = sorted(
        (
            entry
            for entry in (board or {}).values()
            if isinstance(entry, Mapping) and _number(entry.get("elo")) is not None
        ),
        key=lambda entry: -float(entry["elo"]),
    )
    for position, entry in enumerate(ranked, start=1):
        elo = _number(entry.get("elo"))
        if elo is None:
            continue
        low = _number(entry.get("ci95_lower"))
        high = _number(entry.get("ci95_upper"))
        record: dict[str, Any] = {
            "model": str(entry.get("name") or ""),
            "elo": round(float(elo), 1),
            "elo_interval": (
                {"low": round(float(low), 1), "high": round(float(high), 1)}
                if low is not None and high is not None
                else {}
            ),
            "rank": position,
            "rank_range": "",
            "anchor": False,
            "cost_per_task": None,
        }
        entries.append(record)
    return {
        "schema": aa_3d.SCHEMA,
        "schema_version": 1,
        "benchmark": aa_3d.BENCHMARK,
        "benchmark_version": "public-pages",
        "source_url": aa_3d.SOURCE_URL,
        "observed_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)
        ),
        "completeness": {
            "complete": True,
            "scope": "entire_displayed_leaderboard",
            "records": len(entries),
        },
        "records": entries,
    }


def write_snapshot(path: str | Path, document: Mapping[str, Any]) -> bool:
    """Write the pulled snapshot, and say whether it changed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=1, sort_keys=True, default=str, allow_nan=False)
    try:
        if target.read_text(encoding="utf-8") == payload:
            return False
    except OSError:
        pass
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(payload + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)
    return True


def read_model_page(url: str) -> dict[str, Any]:
    """Read one model page, or say why it could not be read.

    The model page publishes the cost per task of a model the leaderboard
    does not carry. One GET per model, and the published number: a cost is
    never estimated.
    """
    return _fetch(url)


def catalog_slugs(path: str | Path) -> list[str]:
    """The models the live catalog offers.

    A model nobody uses is not worth a four megabyte page, so the pull
    reads the pages of these models only.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(document, dict):
        return []
    found: list[str] = []
    for entry in document.values():
        if not isinstance(entry, dict):
            continue
        models = entry.get("models")
        if not isinstance(models, dict):
            continue
        found.extend(str(model) for model in models)
    return sorted(set(found))


def refresh(
    cache_path: str | Path,
    *,
    now: float | None = None,
    read: Any = None,
    model_pages: Any = None,
    aa3d_path: str | Path | None = None,
    catalog_slugs: Iterable[str] = (),
) -> dict[str, Any]:
    """Refresh the cache from the public pages, at most once a day.

    A cache that is still fresh is left alone. A fetch that is blocked or
    that fails keeps the last good snapshot: the cache is not replaced with
    an empty one, and the blocked state is recorded.

    The AA-3D board is written as soon as its page has been read and
    parsed, before any model page is read. A model page that is slow, that
    times out or that fails cannot lose it, and a board that could not be
    read leaves the last good board alone without holding the quality
    cache back.
    """
    moment = time.time() if now is None else float(now)
    current = aa.load_cache(cache_path, moment)
    aa3d_usable = True
    if aa3d_path is not None:
        # The 3D tier reads the AA-3D file. A fresh main cache must not skip
        # a pull that has never written it, or the 3D tier stays empty.
        import aa_3d

        aa3d_usable = (aa_3d.load_cache(str(aa3d_path), moment) or {}).get("status") == "ok"
    if current.get("status") == "ok" and aa3d_usable:
        # The cache is fresh: the pull runs once a day, and the collector
        # reads it every five minutes.
        return {
            "status": "ok",
            "reason": "the cache is still fresh",
            "changed": False,
            "new_models": 0,
            "changed_models": 0,
            "model_page_fetches": 0,
            "model_page_skipped": 0,
        }
    previous = {}
    try:
        previous = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    def write_aa3d(board: Mapping[str, Any]) -> None:
        """Write the AA-3D board, now, before the model pages are read."""
        if aa3d_path is not None:
            write_snapshot(aa3d_path, board)

    cached_costs = previous.get("model_page_costs")
    document = pull(
        read=read,
        model_pages=model_pages,
        catalog_slugs=catalog_slugs,
        cached_costs=cached_costs if isinstance(cached_costs, Mapping) else {},
        write_aa3d=write_aa3d,
    )
    if document.get("quality_blocked"):
        # A page the quality records come from was blocked. The last good
        # snapshot is kept: a blocked page is not a reason to publish an
        # empty cache, and nothing is retried to get around it.
        return {
            "status": "blocked",
            "reason": "a public page answered with a challenge",
            "blocked": list(document.get("quality_blocked") or []),
            "changed": False,
            "new_models": 0,
            "changed_models": 0,
            "model_page_fetches": int(document.get("model_page_fetches") or 0),
            "model_page_skipped": int(document.get("model_page_skipped") or 0),
        }
    difference = aa_diff.diff(previous, document)
    document.pop("aa3d", None)
    page_costs = document.pop("model_page_costs", None)
    fetches = int(document.pop("model_page_fetches", 0) or 0)
    skipped = int(document.get("model_page_skipped") or 0)
    # The new and the changed models travel with the cache, so the
    # collector publishes them without reading the old pull.
    document = {
        **document,
        "new_models": list(difference.get("added") or []),
        "changed_models": [
            {"slug": slug, "name": entry.get("name") or ""}
            for slug, entry in sorted((difference.get("changed") or {}).items())
        ],
        # The model page costs travel with the cache, so a model whose cost
        # is known is never read again.
        "model_page_costs": {
            **(previous.get("model_page_costs") or {}),
            **(page_costs or {}),
        },
    }
    changed = write_snapshot(cache_path, document)
    return {
        "status": "ok",
        "reason": "",
        "changed": changed,
        "records": len(document.get("records") or []),
        "new_models": len(difference.get("added") or []),
        "changed_models": len(difference.get("changed") or {}),
        "removed_models": len(difference.get("removed") or []),
        "model_page_fetches": fetches,
        # The model pages that were not read, and the budget of the run.
        "model_page_skipped": skipped,
        "model_page_budget_seconds": int(
            document.get("model_page_budget_seconds") or 0
        ),
        "model_page_budget_used_seconds": float(
            document.get("model_page_budget_used_seconds") or 0.0
        ),
        "new_model_names": [
            entry.get("name") or entry.get("slug")
            for entry in (difference.get("added") or [])
        ],
        "diff": difference,
    }


def main(argv: list[str] | None = None) -> int:
    """Pull the public pages into the cache."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="aa_pull.py",
        description="Pull the Artificial Analysis public pages into the cache.",
    )
    parser.add_argument("--output", required=True, help="The cache to write.")
    parser.add_argument(
        "--aa3d-output",
        default="",
        help="The AA-3D board cache to write, beside the quality cache.",
    )
    parser.add_argument(
        "--catalog",
        default="",
        help=(
            "The live model catalog. Only the models it offers have their "
            "model page read."
        ),
    )
    parser.add_argument(
        "--model-pages",
        action="store_true",
        help=(
            "Read the model page of every model the leaderboard does not "
            "carry, for the cost per task the page publishes."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    def pages(slug: str) -> dict[str, Any]:
        if not args.model_pages:
            return {}
        return read_model_page(f"https://artificialanalysis.ai/models/{slug}")

    if args.dry_run:
        document = pull(model_pages=pages if args.model_pages else None)
        print(
            json.dumps(
                {
                    "status": document.get("status"),
                    "records": len(document.get("records") or []),
                    "blocked": document.get("blocked") or [],
                }
            )
        )
        return 0
    result = refresh(
        args.output,
        model_pages=pages if args.model_pages else None,
        aa3d_path=args.aa3d_output or None,
        catalog_slugs=catalog_slugs(args.catalog) if args.catalog else (),
    )
    print(json.dumps({key: value for key, value in result.items() if key != "diff"}))
    return 0 if result.get("status") == "ok" else 2


if __name__ == "__main__":  # pragma: no cover - the CLI entry point
    raise SystemExit(main())

