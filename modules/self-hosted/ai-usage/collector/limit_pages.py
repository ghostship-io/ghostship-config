"""Refresh the public provider limit pages through the free inference pool.

The pages are public data. A free-pool job extracts structured rows; this
module validates the schema, diffs the rows against the last dated values, and
writes the state the collector reads. A failed or garbage extraction keeps the
last good rows and marks them stale.

This is deliberately a *public* job: no account page, credential or workspace
identifier is read here. The private Command Code usage page stays on the
browser path.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

SCHEMA = "ghostship.limit-pages/v1"
DEFAULT_STATE_PATH = "/var/lib/ghostship-ai-usage/page-limits.json"
MAX_AGE_SECONDS = 12 * 3600.0
RETRY_AFTER_SECONDS = 3600.0

PAGES = {
    "opencode-go": "https://opencode.ai/go",
    "commandCode": "https://commandcode.ai/docs/plans/goat",
    "ollama": "https://docs.ollama.com/cloud",
    "codex": "https://developers.openai.com/codex/pricing",
    "claude": "https://code.claude.com/docs/en/costs",
    "antigravity": "https://antigravity.google/docs",
    "grok": "https://docs.x.ai/docs/models",
}

WINDOWS = {"session", "weekly", "monthly", "minute", "daily"}
UNITS = {"requests", "tokens", "share"}
PROMPT = """Read the public provider limit page {url}.
Return JSON only: {{"rows": [{{"provider": "{provider}", "model": "<model id or *>",
"window": "session|weekly|monthly|minute|daily", "budget": <number or null>,
"unit": "requests|tokens|share", "estimate": <true|false>, "source": "{url}"}}]}}.
A number the page does not publish is null, never invented. Do not read an
account page, a credential or a private workspace. If the page does not
publish per-model limits, return one row per plan window with model "*"."""


def runner_from_agent(agent: str, timeout: float = 600.0) -> Callable[[str, str], str]:
    """A runner that submits each page to the free inference pool."""

    def run(provider: str, url: str) -> str:
        prompt = PROMPT.format(url=url, provider=provider)
        command = [
            agent, "free-inference", "run", "--json",
            "--profile", "research", "--sensitivity", "public",
            "--prompt", prompt,
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"the free-pool job failed ({result.returncode})")
        return result.stdout

    return run


def _text(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def parse(text: str) -> list[dict[str, Any]]:
    """The rows of one extraction, or an empty list when it is not JSON."""
    body = _text(text)
    document = None
    try:
        document = json.loads(body)
    except ValueError:
        match = re.search(r"\{.*\}", body, re.S)
        if match:
            try:
                document = json.loads(match.group(0))
            except ValueError:
                document = None
    if isinstance(document, list):
        document = {"rows": document}
    if not isinstance(document, Mapping):
        return []
    rows = document.get("rows")
    return rows if isinstance(rows, list) else []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def validate(rows: Iterable[Any], provider: str, source: str) -> list[dict[str, Any]]:
    """Keep only the bounded, well-typed rows of one page."""
    kept = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("provider") or provider)
        model = str(row.get("model") or "").strip()
        window = str(row.get("window") or "").strip().lower()
        unit = str(row.get("unit") or "").strip().lower()
        budget = _number(row.get("budget"))
        if (name != provider or not model or len(model) > 120 or window not in WINDOWS
                or unit not in UNITS or (budget is not None and budget < 0)
                or (row.get("budget") is not None and budget is None)):
            continue
        kept.append({
            "provider": name,
            "model": model,
            "window": window,
            "budget": budget,
            "unit": unit,
            "estimate": bool(row.get("estimate")),
            "source": source,
        })
    return kept


def _load(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def _save(path: str | os.PathLike[str] | None, state: Mapping[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps(dict(state), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        pass


def diff(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, int]:
    """How many rows were added, removed or changed."""
    before = {(row["provider"], row["model"], row["window"], row["unit"]): row for row in old}
    after = {(row["provider"], row["model"], row["window"], row["unit"]): row for row in new}
    return {
        "added": len(set(after) - set(before)),
        "removed": len(set(before) - set(after)),
        "changed": sum(1 for key in set(before) & set(after) if before[key] != after[key]),
    }


def refresh(
    now: float,
    state_path: str | os.PathLike[str] | None = DEFAULT_STATE_PATH,
    run: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Refresh each public page, keeping the last good rows on a failure."""
    previous = _load(state_path)
    old_rows = [row for row in previous.get("rows") or [] if isinstance(row, Mapping)]
    rows = list(old_rows)
    sources = dict(previous.get("sources") or {})
    changed = {"added": 0, "removed": 0, "changed": 0}
    for provider, url in PAGES.items():
        if run is None:
            sources[provider] = {**sources.get(provider, {}), "status": "not_run", "checked_at": None}
            continue
        try:
            extracted = parse(run(provider, url))
            valid = validate(extracted, provider, url)
        except (OSError, RuntimeError, ValueError, TypeError):
            valid = []
        if not valid:
            old = [row for row in rows if row.get("provider") == provider]
            sources[provider] = {
                "status": "stale" if old else "unavailable",
                "checked_at": (sources.get(provider) or {}).get("checked_at"),
                "last_attempt": now,
                "reason": "the extraction was empty or invalid",
            }
            continue
        rows = [row for row in rows if row.get("provider") != provider]
        rows.extend(valid)
        delta = diff([row for row in old_rows if row.get("provider") == provider], valid)
        for key, value in delta.items():
            changed[key] += value
        sources[provider] = {
            "status": "ok",
            "checked_at": now,
            "last_attempt": now,
            "rows": len(valid),
            "reason": "",
        }
    state = {
        "schema": SCHEMA,
        "checked_at": now,
        "stale": any(source.get("status") != "ok" for source in sources.values()),
        "sources": sources,
        "changed": changed,
        "rows": rows,
    }
    _save(state_path, state)
    return state


def read(now: float, state_path: str | os.PathLike[str] | None = DEFAULT_STATE_PATH,
         max_age_seconds: float = MAX_AGE_SECONDS) -> dict[str, Any]:
    """The dated page rows, with the health of each page."""
    state = _load(state_path)
    if not state:
        return {"schema": SCHEMA, "checked_at": None, "stale": True, "sources": {}, "rows": []}
    if state.get("schema") != SCHEMA:
        return {"schema": SCHEMA, "checked_at": None, "stale": True, "sources": {}, "rows": []}
    checked = state.get("checked_at")
    age = None if not isinstance(checked, (int, float)) or isinstance(checked, bool) else float(now) - float(checked)
    result = dict(state)
    result["age_seconds"] = age
    result["stale"] = bool(state.get("stale")) or age is None or age > max_age_seconds
    return result


def rows_for(state: Mapping[str, Any] | None, provider: str, model: str) -> list[dict[str, Any]]:
    """The dated rows of one route, matching ``*`` and the exact model."""
    rows = []
    for row in (state or {}).get("rows") or []:
        if not isinstance(row, Mapping) or row.get("provider") != provider:
            continue
        wanted = str(row.get("model") or "")
        if wanted not in ("*", str(model)):
            continue
        rows.append(dict(row))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--agent", help="The free-pool agent executable")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    if not args.refresh:
        state = read(__import__("time").time(), args.state)
        json.dump(state, sys.stdout, indent=1, sort_keys=True)
        return 0
    run = runner_from_agent(args.agent, args.timeout) if args.agent else None
    state = refresh(__import__("time").time(), args.state, run)
    print(json.dumps({key: state[key] for key in ("schema", "checked_at", "stale", "changed")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
