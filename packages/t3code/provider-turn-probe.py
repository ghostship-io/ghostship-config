#!/usr/bin/env python3
"""Run the real approved-route tool-loop proof in an explicit candidate workspace."""

import argparse
import json
import os
from pathlib import Path
import sys


def safe_failure_code(result):
    """Project prove() failures to a bounded category without exposing detail."""
    detail = result.get("detail")
    outcome = result.get("outcome")
    if isinstance(detail, str) and "model unavailable" in detail.lower().replace("-", " ").replace("_", " "):
        return "model-unavailable"
    if isinstance(outcome, str) and outcome.lower().replace("_", "-") in {
        "execution", "timeout", "provider-schema", "invalid-request", "quota",
        "no-tool-call",
    }:
        return outcome.lower().replace("_", "-")
    return "proof-failed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("route")
    parser.add_argument("--wait", type=float, default=180)
    args = parser.parse_args()

    agent_tools = (os.environ.get("GHOSTSHIP_TOOLS_ROOT")
                   or os.environ.get("GHOSTSHIP_AGENT_ROOT"))
    if not agent_tools:
        parser.error("candidate agent tools path is unavailable")
    sys.path.insert(0, str(Path(agent_tools) / "tools/python"))

    from ghostship_t3.bridge import Bridge
    from ghostship_t3.prove import prove

    class CandidateBridge(Bridge):
        def submit(self, prompt, **kwargs):
            kwargs.setdefault("workspace_root", "/workspace")
            return super().submit(prompt, **kwargs)

    result = prove({"route": args.route, "wait": args.wait}, client=CandidateBridge())
    output = {
        "provider": result.get("provider"),
        "model": result.get("model"),
        "instance": result.get("instance"),
        "outcome": result.get("outcome"),
        "elapsed_s": result.get("elapsed_s"),
        "settled": result.get("settled"),
    }
    if result.get("outcome") != "passed" or result.get("settled") is not True:
        output["error"] = {"code": safe_failure_code(result)}
    print(json.dumps(output, sort_keys=True))
    return 0 if result.get("outcome") == "passed" and result.get("settled") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
