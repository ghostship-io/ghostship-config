"""The daily evaluation: read the measured evidence and publish the cache.

The collector reports what the accounts can do. This procedure reports what
the models are worth, and it writes the state the collector reads:

* the Artificial Analysis cache, read from the free endpoint by the service
  library that owns the API clients of this fleet. The collector only reads
  the cache, so the free request budget belongs to this one place.
* the admission evidence of the free inference pool, read through the
  broker's read surface. The pool already runs revisioned workload benches
  and keeps their results; nothing new is built for them.

The procedure is idempotent and adds no service, no database, and no
listener. The contract is in EVALUATION.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "collector"))

import aa  # noqa: E402
import codes  # noqa: E402
import pool as pool_module  # noqa: E402
from util import read_env_file  # noqa: E402

STATE_DIR = "/var/lib/ghostship-ai-usage"
AA_CACHE = f"{STATE_DIR}/artificial-analysis.json"
ADMISSION_STATE = f"{STATE_DIR}/admission.json"
FACTS_PATH = f"{STATE_DIR}/facts.json"
SECRETS_ENV_FILE = "/run/ghostship-secrets/t3code.env"
POOL_SERVER_FILE = "/run/ghostship-integrations/inference-server.json"
POOL_TOKEN_FILE = "/run/ghostship-integrations/inference-token"
T3_HOME = "/srv/apps/t3code/home"

# The contract the public pages have to satisfy. There is no key, no
# account, and no paid feature: the pull reads public pages with ordinary
# GETs, and it keeps the last good snapshot when a page is blocked.
FEED_CONTRACT = {
    "endpoint": "GET https://artificialanalysis.ai/leaderboards/models",
    "plan": "public",
    "pages": "every page, with has_more and total_pages",
    "output": {
        "intelligence_index_version": "the major.minor of the intelligence index",
        "fetched_at": "UTC ISO-8601 of the read",
        "fetched_at_epoch": "the same moment as a number",
        "records": [
            {
                "model": "the exact model name of the feed",
                "provider": "the model creator of the feed",
                "release_date": "the release date of the feed",
                "indices": {
                    "intelligence_index": "number",
                    "coding_index": "number",
                    "agentic_index": "number",
                    "engineering_index": "number",
                },
                "prices": {"input": "number", "output": "number", "cache_read": "number"},
                "cost_per_task": "number",
                "median_performance": "number",
            }
        ],
    },
    "rules": [
        "only the free endpoint is read",
        "the cost per task is never used as a token price",
        "a model the feed does not list is unknown, not bad",
        "a record of another index version is not merged with the current one",
    ],
}


def read_feed(cache_path: str, now: float) -> dict[str, Any]:
    """Read the cached feed, and report the gap when there is none.

    The fetch belongs to the registered client of the feed, which the root of
    the service library owns. This procedure never calls an invented command
    and never registers a second client: it reads the cache the client writes
    and reports what is missing.
    """
    cache = aa.load_cache(cache_path, now)
    if cache.get("status") == "ok":
        return {
            "status": "ok",
            "reason": codes.OK,
            "intelligence_index_version": cache.get("index_version"),
            "fetched_at": cache.get("fetched_at"),
            "fetched_at_epoch": cache.get("fetched_at_epoch"),
            "records": cache.get("records") or [],
            # The models the last pull found that the one before it did not
            # carry, and the models whose measurement changed. They are the
            # re-ranking trigger, and they travel with the cache.
            "new_models": cache.get("new_models") or [],
            "changed_models": cache.get("changed_models") or [],
        }
    return {
        "status": str(cache.get("status") or "missing"),
        "reason": str(cache.get("reason") or codes.MISSING_CREDENTIALS),
        "intelligence_index_version": aa.INTELLIGENCE_INDEX_VERSION,
        "fetched_at": None,
        "fetched_at_epoch": None,
        "records": [],
        "contract": FEED_CONTRACT,
    }


def write_json(path: str, document: Any) -> None:
    """Write a document atomically."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(
        json.dumps(document, indent=1, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)


def read_admissions(now: float) -> dict[str, Any]:
    """Read the measured admission results of the free inference pool."""
    try:
        socket_path = pool_module.resolve_socket(POOL_SERVER_FILE, T3_HOME)
        token = pool_module.resolve_token(POOL_TOKEN_FILE, T3_HOME)
        page = pool_module.bridge_call(
            socket_path, token, "status", {"op": "admissions", "offset": 0, "limit": 200}
        )
    except Exception:  # noqa: BLE001 - the reason must stay a code
        return {
            "status": "error",
            "reason": codes.UNAVAILABLE,
            "observed_at_epoch": None,
            "admissions": [],
        }
    rows = page.get("admissions")
    return {
        "status": "ok",
        "reason": codes.OK,
        "observed_at_epoch": now,
        "admissions": rows if isinstance(rows, list) else [],
        "benchmarks": page.get("benchmarks") or [],
    }


def build_facts(
    feed: dict[str, Any],
    admissions: dict[str, Any],
    existing: dict[str, Any],
    now: float,
) -> dict[str, Any]:
    """Build the durable facts out of the feed and the admission evidence.

    A fact is reused when it is still current: the same identity, the same
    benchmark version, and not stale. A model that the feed does not list
    waits, visibly, and is rechecked later instead of being researched again
    every day.
    """
    facts_module = __import__("facts")
    built: dict[str, Any] = {}
    records = feed.get("records") if isinstance(feed, dict) else None
    for record in records or []:
        if not isinstance(record, dict):
            continue
        model = str(record.get("model") or "")
        provider = str(record.get("provider") or "")
        if not model:
            continue
        identity = facts_module.identity_key(provider, model)
        current = existing.get(identity)
        needed, why = facts_module.needs_research(current, identity, now)
        if not needed and isinstance(current, dict):
            built[identity] = current
            continue
        fact = facts_module.make_fact(
            provider=provider,
            model=model,
            canonical_identity=model,
            indices=record.get("indices") or {},
            cost_per_task=record.get("cost_per_task"),
            token_prices=record.get("prices") or {},
            throughput=(
                {"median_performance": record.get("median_performance")}
                if record.get("median_performance") is not None
                else {}
            ),
            released_at=str(record.get("release_date") or ""),
            benchmark_id=str(record.get("slug") or model),
            brief_url="https://artificialanalysis.ai/models",
            source="measured",
            confidence=1.0,
            basis="the Artificial Analysis feed",
            now=now,
        )
        fact["research_reason"] = why
        built[identity] = fact
    # The measured admission evidence of the pool travels with the facts.
    rows = admissions.get("admissions") if isinstance(admissions, dict) else None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not provider or not model:
            continue
        identity = facts_module.identity_key(provider, model)
        fact = built.get(identity) or existing.get(identity)
        if not isinstance(fact, dict):
            fact = facts_module.make_fact(
                provider=provider,
                model=model,
                source="measured",
                confidence=1.0,
                basis="the admission bench of the free inference pool",
                now=now,
            )
        admission = {
            "workload": str(row.get("workload") or ""),
            "admitted": bool(row.get("admitted")),
            "score": row.get("score"),
            "at": row.get("at"),
        }
        measured = fact.setdefault("admission_evidence", [])
        if admission not in measured:
            measured.append(admission)
        built[identity] = fact
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the daily model evaluation.")
    parser.add_argument("--aa-cache", default=AA_CACHE)
    parser.add_argument("--admission-state", default=ADMISSION_STATE)
    parser.add_argument("--facts", default=FACTS_PATH)
    parser.add_argument("--secrets-env", default=SECRETS_ENV_FILE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    now = time.time()
    feed = read_feed(args.aa_cache, now)
    admissions = read_admissions(now)
    existing: dict[str, Any] = {}
    try:
        document = json.loads(Path(args.facts).read_text(encoding="utf-8"))
        if isinstance(document, dict) and isinstance(document.get("facts"), dict):
            existing = document["facts"]
    except (OSError, ValueError):
        existing = {}
    facts = build_facts(feed, admissions, existing, now)
    if not args.dry_run:
        write_json(args.aa_cache, feed)
        write_json(args.admission_state, admissions)
        write_json(args.facts, {"facts": facts, "updated_at_epoch": now})
    print(
        json.dumps(
            {
                "feed": {k: v for k, v in feed.items() if k != "records"},
                "feed_records": len(feed.get("records") or []),
                "admissions": {k: v for k, v in admissions.items() if k != "admissions"},
                "admission_rows": len(admissions.get("admissions") or []),
                "facts": len(facts),
            },
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
