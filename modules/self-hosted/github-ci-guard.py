"""Host-owned admission: refuse foreign PR sources before workflow steps."""
import json
import os
from pathlib import Path
import sys


def allowed(expected, environment):
    if environment.get("GITHUB_REPOSITORY") != expected:
        return False
    event = environment.get("GITHUB_EVENT_NAME")
    if event not in ("pull_request", "workflow_dispatch"):
        return False
    try:
        path = Path(environment["GITHUB_EVENT_PATH"])
        if path.stat().st_size > 2 * 1024 * 1024:
            return False
        payload = json.loads(path.read_text())
        if payload["repository"]["full_name"] != expected:
            return False
        if event == "pull_request":
            pr = payload["pull_request"]
            return (pr["base"]["repo"]["full_name"] == expected
                    and pr["head"]["repo"]["full_name"] == expected)
        return True  # A dispatch ref belongs to this repository; no foreign PR.
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not allowed(args[0], os.environ):
        print("github-ci: refusing a foreign or unverified source", file=sys.stderr)
        return 1
    print("github-ci: repository source verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
