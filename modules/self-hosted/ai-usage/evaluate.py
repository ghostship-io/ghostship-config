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
SECRETS_ENV_FILE = "/run/ghostship-secrets/t3code.env"
POOL_SERVER_FILE = "/run/ghostship-integrations/inference-server.json"
POOL_TOKEN_FILE = "/run/ghostship-integrations/inference-token"
T3_HOME = "/srv/apps/t3code/home"

# The key of the free feed. It belongs to the secret catalog like every other
# provider key. There is no account, no plan, and no paid feature.
AA_KEY_NAME = "ARTIFICIAL_ANALYSIS_API_KEY"


def read_feed(env_file: str, now: float) -> dict[str, Any]:
    """Read the free Artificial Analysis feed into the cache.

    The fetch is done by the service library of this fleet when it has a
    client for the feed. Without that client, or without a key, the cache
    records the gap: no score is invented and nothing is faked.
    """
    key = read_env_file(env_file).get(AA_KEY_NAME, "")
    if not key:
        return {
            "status": "missing",
            "reason": codes.MISSING_CREDENTIALS,
            "intelligence_index_version": aa.INTELLIGENCE_INDEX_VERSION,
            "fetched_at": None,
            "fetched_at_epoch": None,
            "records": [],
        }
    # The client of the feed is owned by the service library. It is reached
    # through the ordinary command path of that library, so the request
    # budget, the key handling, and the rate limits stay in one place.
    command = [
        "/home/t3code/.local/bin/agent",
        "pp",
        "artificialanalysis",
        "models",
        "--free",
        "--json",
    ]
    import subprocess

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "status": "error",
            "reason": codes.UNAVAILABLE,
            "intelligence_index_version": aa.INTELLIGENCE_INDEX_VERSION,
            "fetched_at": None,
            "fetched_at_epoch": None,
            "records": [],
        }
    if result.returncode != 0:
        return {
            "status": "error",
            "reason": codes.UNAVAILABLE,
            "intelligence_index_version": aa.INTELLIGENCE_INDEX_VERSION,
            "fetched_at": None,
            "fetched_at_epoch": None,
            "records": [],
        }
    try:
        document = json.loads(result.stdout)
    except ValueError:
        return {
            "status": "error",
            "reason": codes.INVALID_RESPONSE,
            "intelligence_index_version": aa.INTELLIGENCE_INDEX_VERSION,
            "fetched_at": None,
            "fetched_at_epoch": None,
            "records": [],
        }
    records = document.get("records") if isinstance(document, dict) else None
    return {
        "status": "ok",
        "reason": codes.OK,
        "intelligence_index_version": aa.INTELLIGENCE_INDEX_VERSION,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "fetched_at_epoch": now,
        "records": records if isinstance(records, list) else [],
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the daily model evaluation.")
    parser.add_argument("--aa-cache", default=AA_CACHE)
    parser.add_argument("--admission-state", default=ADMISSION_STATE)
    parser.add_argument("--secrets-env", default=SECRETS_ENV_FILE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    now = time.time()
    feed = read_feed(args.secrets_env, now)
    admissions = read_admissions(now)
    if not args.dry_run:
        write_json(args.aa_cache, feed)
        write_json(args.admission_state, admissions)
    print(
        json.dumps(
            {
                "feed": {k: v for k, v in feed.items() if k != "records"},
                "feed_records": len(feed.get("records") or []),
                "admissions": {k: v for k, v in admissions.items() if k != "admissions"},
                "admission_rows": len(admissions.get("admissions") or []),
            },
            indent=1,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
