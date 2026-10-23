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
fails cannot lose it.

Every read has a hard limit of its own, and the run has a hard deadline
that covers every read, the source pages included: a read that could not
start inside the deadline is skipped and counted, and the run writes
what it has and stops. One line per read says how long it took and how
it went, and the final line says how long the run took.

The pull runs at most once a day. The collector itself never calls the
network: it reads the cache the pull wrote.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
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
MAX_MODEL_PAGE_FETCHES = 4

# The deadline of the whole run, in seconds, from the start of the process.
# It covers every read of the run, the source pages included, and it stays
# well below the timeout of the unit that runs the pull: a run that is
# killed at its timeout writes nothing at all.
RUN_DEADLINE_SECONDS = 480.0

# The hard limit of one read, in seconds: the connect, the headers and the
# whole body. A socket timeout bounds one blocking operation, so a page
# that trickles or that stalls can take far longer than that; a read that
# is not finished in this time is abandoned and reported as a failed read.
READ_DEADLINE_SECONDS = 60.0

# The body of a page is read in chunks of this size, so a read that was
# abandoned stops at the next chunk.
READ_CHUNK_BYTES = 256 * 1024

# The clock the deadline of the run and the limit of a read are measured
# with. A test moves it by hand: the pull reads pages over the network, and
# a slow page has to be a number and not a minute of waiting.
CLOCK: Any = time.monotonic

# A deprecated model is superseded, not changed: its published cost is read
# once and never again. A model that is not deprecated but is absent from
# the leaderboard may still change, so it is read again - but not more than
# once a week.
MODEL_PAGE_REFETCH_SECONDS = 7 * 24 * 3600.0


def _log_read(label: str, elapsed: float, bytes_read: int, outcome: str) -> None:
    """One line per read: what was read, how long it took, how it went.

    The line carries no page content: the pull reads public pages, and a
    log is not a place for a page.
    """
    sys.stderr.write(
        f"aa-pull read {label} elapsed={elapsed:.2f} "
        f"bytes={int(bytes_read)} outcome={outcome}\n"
    )
    sys.stderr.flush()


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


def _fetch(url: str, *, limit: float = READ_DEADLINE_SECONDS) -> dict[str, Any]:
    """Read one public page, or say why it could not be read.

    The read has a hard limit of `limit` seconds for the whole read: the
    connect, the headers and the body. A socket timeout bounds one
    blocking operation, so a page that trickles or that stalls can take
    far longer than that; the read is therefore done apart and the wait
    for it is bounded. A read that is not finished in time is abandoned
    and reported as a failed read, and nothing is retried.

    A page that is blocked, that answers with a challenge, or that is not
    there is recorded as blocked. There is no retry: the pull is a read of
    public pages, and a refused read stays refused.
    """
    outcome: dict[str, Any] = {}
    finished = threading.Event()
    abandoned = threading.Event()

    def worker() -> None:
        try:
            outcome["reading"] = _read_once(url, abandoned)
        except BaseException as error:  # noqa: BLE001 - the read may fail in any way
            outcome["error"] = error
        finally:
            finished.set()

    thread = threading.Thread(target=worker, name="aa-pull-read", daemon=True)
    thread.start()
    if not finished.wait(limit):
        # The read is abandoned: the thread stops at the next chunk, and
        # the socket it holds is closed with it.
        abandoned.set()
        # The read is abandoned. The socket it holds is closed when the
        # process ends.
        return {
            "url": url,
            "http_status": None,
            "bytes": 0,
            "blocked": True,
            "error": "deadline",
        }
    reading = outcome.get("reading")
    if isinstance(reading, dict):
        return reading
    error = outcome.get("error")
    return {
        "url": url,
        "http_status": None,
        "bytes": 0,
        "blocked": True,
        "error": type(error).__name__ if error is not None else "the read failed",
    }


def _read_body(response: Any, abandoned: threading.Event | None = None) -> bytes:
    """The body of a page, in chunks, and no more than the reader accepts.

    The read stops as soon as the read it belongs to has been abandoned,
    and it never buffers more than the largest page the reader accepts.
    """
    parts: list[bytes] = []
    total = 0
    while total <= MAX_BYTES:
        if abandoned is not None and abandoned.is_set():
            break
        chunk = response.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        parts.append(chunk)
        total += len(chunk)
    return b"".join(parts)


def _read_once(url: str, abandoned: threading.Event | None = None) -> dict[str, Any]:
    """Read one public page with the socket timeout, and no deadline.

    This is the read itself; `_fetch` gives it a deadline. The body is
    read in chunks, so a read that was abandoned stops at the next chunk
    and lets go of its socket and its memory.
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
            body = _read_body(response, abandoned)
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


class _RunDeadline:
    """The deadline of one pull, and the reads it skipped.

    The deadline covers every read of the run, the source pages included.
    A read is started only while a whole read's time is left, so a read
    that starts can still finish before the deadline. The reads that are
    not started are counted, so a run that skipped them says so.

    The clock is injected: a test reads the pages of a fixture and moves
    the clock by hand, with no network and no sleeping.
    """

    def __init__(
        self,
        clock: Any,
        *,
        started: float | None = None,
        deadline_seconds: float = RUN_DEADLINE_SECONDS,
        read_seconds: float = READ_DEADLINE_SECONDS,
    ) -> None:
        self._clock = clock
        self._deadline_seconds = float(deadline_seconds)
        self.read_seconds = float(read_seconds)
        self.started = float(clock()) if started is None else float(started)
        # Every read that was not started.
        self.skipped = 0
        # The model pages that were not read.
        self.model_skipped = 0
        # True when the deadline kept a read from starting.
        self.deadline_reached = False

    def elapsed(self) -> float:
        """The seconds the run has taken so far."""
        return float(self._clock()) - self.started

    def remaining(self) -> float:
        """The seconds of the deadline that are left."""
        return self._deadline_seconds - self.elapsed()

    def allow(self) -> bool:
        """True when a read may start now."""
        return self.remaining() >= self.read_seconds

    def skip(self) -> None:
        """Count a read that the deadline kept from starting."""
        self.skipped += 1
        self.deadline_reached = True


def aa3d_board_is_complete(board: Mapping[str, Any], html: str) -> bool:
    """True when the page shows the whole board that it scores.

    The board is the entire displayed leaderboard, and the ranks and the
    normalisation of the 3D tier are computed over it. The rows the page
    renders and the models it scores must be the same ones: a page that
    lost a row, on either side of it, is not a board, and the numbers
    would be computed over a part of it.

    The names must be unique as well: the 3D reader refuses a board with
    two measurements of the same model.
    """
    scored = [
        str(entry.get("name") or "")
        for entry in (board or {}).values()
        if isinstance(entry, Mapping) and _number(entry.get("elo")) is not None
    ]
    if len(set(scored)) != len(scored):
        return False
    rows = list(_aa3d_table(html or ""))
    if len(scored) != len(rows):
        return False
    return sorted(scored) == sorted(rows)


def _read_model_pages(
    records: dict[str, dict[str, Any]],
    leaderboard: Mapping[str, Any],
    *,
    model_pages: Any = None,
    offered: Iterable[str] = (),
    known: Mapping[str, Any] | None = None,
    now: float | None = None,
    deadline: _RunDeadline | None = None,
) -> tuple[dict[str, Any], int]:
    """The published cost of the models whose page has to be read.

    A model page is about four megabytes, so the page is read only for a
    model the live catalog still offers, only when its cost is not known
    already, and at most this many times in one run. The cost of a
    deprecated model never changes, so it is read once and never again; a
    model that is not deprecated is read again at most once a week.

    With a deadline, a page is read only while a whole read's time is
    left, so a page that starts can still finish. The pages that are not
    read are counted, and their models keep the cost they had: a cost that
    was not read is unknown, never zero.

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
            if deadline is not None:
                deadline.skipped += 1
                deadline.model_skipped += 1
            continue
        fetches += 1
        page = model_pages(slug)
        if not page:
            continue
        if deadline is not None and (
            page.get("skipped") or page.get("error") == "deadline"
        ):
            # The page was not read: it was skipped, or it was abandoned
            # after it ran past the limit of a read.
            deadline.model_skipped += 1
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
    started: float | None = None,
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

    `started` is the moment the run started, that is, the start of the
    process: the deadline of the run is measured from it. Every read of
    the run, the source pages included, is inside that deadline, and every
    read is logged: one line per read, without any page content.
    """
    offered = {_normalise(slug) for slug in catalog_slugs or () if str(slug)}
    known = dict(cached_costs or {})
    reader = read or _fetch
    deadline = _RunDeadline(CLOCK, started=started)
    entries: dict[str, dict[str, Any]] = {}
    pages: dict[str, str] = {}

    def timed_read(label: str, call: Any, url: str = "") -> dict[str, Any]:
        """Read one page inside the deadline, and say how the read went.

        A read that could not start inside the deadline is skipped and
        counted. A read that ran past its own limit is abandoned: its
        content is not used, and nothing is retried.
        """
        if not deadline.allow():
            deadline.skip()
            _log_read(label, 0.0, 0, "skipped")
            return {
                "url": url,
                "http_status": None,
                "bytes": 0,
                "blocked": True,
                "error": "deadline",
                "skipped": True,
            }
        began = CLOCK()
        try:
            reading = call()
        except Exception as error:  # noqa: BLE001 - a read may fail in any way
            reading = {
                "url": url,
                "http_status": None,
                "bytes": 0,
                "blocked": True,
                "error": type(error).__name__,
            }
        elapsed = CLOCK() - began
        if not isinstance(reading, dict):
            reading = {
                "url": url,
                "http_status": None,
                "bytes": 0,
                "blocked": True,
                "error": "the read returned nothing",
            }
        if elapsed > deadline.read_seconds:
            # The read ran past the limit of a read: it is abandoned, and
            # its content is not used.
            reading = {
                **{key: value for key, value in reading.items() if key != "text"},
                "blocked": True,
                "error": "deadline",
            }
        if reading.get("skipped"):
            outcome = "skipped"
        elif reading.get("error") == "deadline":
            outcome = "deadline"
        elif reading.get("blocked"):
            outcome = "error"
        else:
            outcome = "ok"
        _log_read(label, elapsed, int(reading.get("bytes") or 0), outcome)
        return reading

    def read_source(key: str, url: str, role: str) -> str:
        """Read one public page, and record how the read went."""
        reading = timed_read(key, lambda: reader(url), url)
        entries[key] = {
            "key": key,
            "url": url,
            "role": role,
            "http_status": reading.get("http_status"),
            "bytes": reading.get("bytes"),
            "blocked": bool(reading.get("blocked")),
            "skipped": bool(reading.get("skipped")),
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
    # The board is written only when the page carries the whole board. A
    # page that lost a row is not a board, and the last good board is kept.
    board_complete = bool(board) and aa3d_board_is_complete(board, aa3d_html)
    if board_complete and board_document.get("records") and write_aa3d is not None:
        write_aa3d(board_document)
    for key, url, role in SOURCES:
        if key == "aa3d":
            continue
        read_source(key, url, role)

    def read_model_page_of(slug: str) -> dict[str, Any]:
        """Read the model page of one model, inside the deadline."""
        url = f"https://artificialanalysis.ai/models/{slug}"
        return timed_read(slug, lambda: model_pages(slug), url)

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
    # many times in one run, and only while the deadline of the run has a
    # whole read's time left. The published number is used as it is
    # published, and a cost is never estimated.
    model_page_costs, fetches = _read_model_pages(
        records,
        leaderboard,
        model_pages=read_model_page_of if model_pages is not None else None,
        offered=offered,
        known=known,
        deadline=deadline,
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
        # The model pages that were not read, the reads the deadline
        # skipped, and the time the run has taken.
        "model_page_skipped": deadline.model_skipped,
        "skipped_reads": deadline.skipped,
        "deadline_reached": deadline.deadline_reached,
        "deadline_seconds": RUN_DEADLINE_SECONDS,
        "total_seconds": round(deadline.elapsed(), 3),
        # The AA-3D board, in the contract the collector reads it in, and
        # whether the page carried the whole board.
        "aa3d": board_document,
        "aa3d_complete": board_complete,
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
    started: float | None = None,
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

    `started` is the moment the run started, that is, the start of the
    process: the deadline of the run is measured from it.
    """
    moment = time.time() if now is None else float(now)
    current = aa.load_cache(cache_path, moment)
    aa3d_usable = True
    if aa3d_path is not None:
        # The 3D tier reads the AA-3D file. A fresh main cache must not skip
        # a pull that has never written it, or the 3D tier stays empty.
        import aa_3d

        aa3d_usable = (aa_3d.load_cache(str(aa3d_path), moment) or {}).get("status") == "ok"
    # Collection tolerates a 36h-old reading; a daily pull must refresh at
    # 24h or it skips a day and leaves the dashboard stale before tomorrow.
    if (current.get("status") == "ok" and aa3d_usable
            and current.get("age_seconds", float('inf')) < 24 * 3600):
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
            "skipped_reads": 0,
            "deadline_reached": False,
            "total_seconds": 0.0,
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
        started=started,
    )
    skipped_pages = [
        entry.get("url")
        for entry in (document.get("sources") or [])
        if entry.get("skipped")
    ]
    if document.get("quality_blocked"):
        # A page the quality records come from was blocked or was skipped.
        # The last good snapshot is kept: a blocked page is not a reason
        # to publish an empty cache, and nothing is retried to get around
        # it.
        return {
            "status": "blocked",
            "reason": (
                "the run reached its deadline before every page was read"
                if skipped_pages
                else "a public page answered with a challenge"
            ),
            "blocked": list(document.get("quality_blocked") or []),
            "changed": False,
            "new_models": 0,
            "changed_models": 0,
            "model_page_fetches": int(document.get("model_page_fetches") or 0),
            "model_page_skipped": int(document.get("model_page_skipped") or 0),
            "skipped_reads": int(document.get("skipped_reads") or 0),
            "deadline_reached": bool(document.get("deadline_reached")),
            "total_seconds": float(document.get("total_seconds") or 0.0),
        }
    difference = aa_diff.diff(previous, document)
    document.pop("aa3d", None)
    page_costs = document.pop("model_page_costs", None)
    fetches = int(document.pop("model_page_fetches", 0) or 0)
    skipped = int(document.get("model_page_skipped") or 0)
    board_complete = bool(document.get("aa3d_complete"))
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
        # The model pages that were not read, the reads the deadline
        # skipped, and the time the run took.
        "model_page_skipped": skipped,
        "skipped_reads": int(document.get("skipped_reads") or 0),
        "deadline_reached": bool(document.get("deadline_reached")),
        "deadline_seconds": int(document.get("deadline_seconds") or 0),
        "total_seconds": float(document.get("total_seconds") or 0.0),
        # Whether the AA-3D page carried the whole board.
        "aa3d_complete": board_complete,
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
    # The deadline of the run is measured from the start of the process.
    started = CLOCK()

    def pages(slug: str) -> dict[str, Any]:
        if not args.model_pages:
            return {}
        return read_model_page(f"https://artificialanalysis.ai/models/{slug}")

    if args.dry_run:
        document = pull(model_pages=pages if args.model_pages else None, started=started)
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
        started=started,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "diff"}))
    # A run that ran out of time is not a failure: it wrote what it had,
    # and the unit must not be marked as failed for that.
    if result.get("status") == "ok" or result.get("deadline_reached"):
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover - the CLI entry point
    raise SystemExit(main())

