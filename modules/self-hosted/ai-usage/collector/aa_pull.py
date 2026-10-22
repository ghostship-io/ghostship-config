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

The pull runs at most once a day. The collector itself never calls the
network: it reads the cache the pull wrote.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import aa

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
        "https://artificialanalysis.ai/evaluations/aa-3d",
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
    release_by_slug = {str(row.get("slug")): row for row in releases if row.get("slug")}
    variant_by_slug = {str(row.get("slug")): row for row in variants if row.get("slug")}
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


def pull(
    *,
    read: Any = None,
    model_pages: Any = None,
) -> dict[str, Any]:
    """Pull the public pages and build the cache document.

    `read` is the function that reads one url and returns the reading of
    the pull module; `model_pages` reads the model page of a model that
    the leaderboard does not carry. Both are injectable, so a test can read
    a fixture without a network.
    """
    reader = read or _fetch
    sources: list[dict[str, Any]] = []
    pages: dict[str, str] = {}
    for key, url, role in SOURCES:
        reading = reader(url)
        sources.append(
            {
                "key": key,
                "url": url,
                "role": role,
                "http_status": reading.get("http_status"),
                "bytes": reading.get("bytes"),
                "blocked": bool(reading.get("blocked")),
                "error": reading.get("error"),
            }
        )
        if reading.get("blocked"):
            continue
        pages[key] = str(reading.get("text") or "")
    leaderboard = parse_leaderboard(pages.get("leaderboard") or "")
    models = parse_models(pages.get("models") or "")
    aa3d = parse_aa3d(pages.get("aa3d") or "")

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
    for slug, entry in aa3d.items():
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
    # A deprecated or leaderboard-absent model that the models page knows
    # and the leaderboard does not: its own page publishes the cost per
    # task. One GET per model, and the published number, never an
    # estimate.
    if model_pages is not None:
        for slug, entry in sorted(records.items()):
            if entry.get("cost_per_task") is not None:
                continue
            if not entry.get("deprecated") and slug in leaderboard:
                continue
            page = model_pages(slug)
            if not page:
                continue
            cost = _cost_in_text(str(page.get("text") or ""))
            if cost is None:
                continue
            entry["cost_per_task"] = cost
            entry["cost_basis"] = COST_BASIS_MODEL_PAGE
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
        "completeness": {
            "scope": "the public pages",
            "complete": not any(entry["blocked"] for entry in sources),
            "pages_fetched": len(pages),
            "total_pages": len(SOURCES),
            "records": len(ordered),
        },
        "records": ordered,
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


import os  # noqa: E402  (used by write_snapshot, kept next to its use)
