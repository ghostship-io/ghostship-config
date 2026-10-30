#!/usr/bin/env python3
"""Run the real approved-route tool-loop proof in an explicit candidate workspace."""

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote


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


PROBE_PROMPT = (
    "This is a bounded T3 tool-loop proof. Use exactly one tool call to list the "
    "top-level files of the current workspace, then reply with exactly "
    "PROBE_PASS. Do not edit files, run commands, install anything or wait. "
    "If you cannot execute a tool call, reply PROBE_FAIL: <short reason>."
)


def has_tool_result(client, thread):
    projection = (client._get(f"/api/orchestration/threads/{quote(thread, safe='')}") or {}).get("projection") or {}
    runs = projection.get("runs") or []
    if len(runs) != 1 or not isinstance(runs[0], dict) or not runs[0].get("id"):
        return False
    run_id = runs[0]["id"]
    items = [item for item in projection.get("turnItems") or []
             if isinstance(item, dict) and item.get("runId") == run_id]
    return any(item.get("type") == "tool_result" and item.get("ok") is True for item in items)


def prove_route(route, wait, client):
    from ghostship_t3.bridge import T3Error
    from ghostship_t3.models import read_document, _selection

    provider, sep, model = route.partition("/")
    if not sep or not provider or not model:
        raise T3Error("route must be provider/model")
    document = read_document()
    selected = _selection(document, time.time())
    target = None
    for row in selected.get("worker") or []:
        native = row.get("native") or {}
        if row.get("provider") == provider and row.get("model") == model and native.get("instanceId") and native.get("model"):
            target = (native["instanceId"], native["model"],
                      {item["id"]: item["value"] for item in native.get("options") or []
                       if isinstance(item, dict) and item.get("id")})
            break
    if target is None:
        for row in document.get("candidates") or []:
            native = row.get("native") or {}
            if row.get("provider") == provider == "opencode-free" and (row.get("model") == model or native.get("model_id") == model):
                target = ("opencode-free", native.get("model_id") or model, {})
                break
    if target is None:
        raise T3Error("route has no live T3 target to prove")

    started = time.monotonic()
    wait = min(600.0, max(1.0, wait))
    thread = None
    result = {"provider": provider, "model": model, "instance": target[0],
              "outcome": "execution", "detail": "submit failed", "settled": False}
    try:
        submitted = client.submit(PROBE_PROMPT, title=f"Tool-loop probe: {route}",
                                  instance_id=target[0], model=target[1], options=target[2] or None,
                                  sensitivity="public", workspace_root="/workspace")
        thread = submitted.get("thread_id")
        if not thread:
            raise T3Error("probe launch returned no thread")
        state = client.status(thread, wait_s=wait)
        status = str(state.get("state") or "").lower()
        detail = " ".join(str(state.get(k) or "") for k in ("last_error", "reply")).lower()
        if state.get("active_turn") and time.monotonic() - started >= wait:
            outcome = "timeout"
        elif (status in ("completed", "done", "idle", "succeeded")
              and "PROBE_PASS" in str(state.get("reply") or "")
              and has_tool_result(client, thread)):
            outcome = "passed"
        elif "schema" in detail:
            outcome = "provider_schema"
        elif "invalid_request" in detail or "invalid request" in detail:
            outcome = "invalid_request"
        elif "rate limit" in detail or "quota" in detail or "429" in detail:
            outcome = "quota"
        elif status in ("failed", "error", "cancelled", "interrupted"):
            outcome = "execution"
        elif status in ("completed", "done", "idle", "succeeded"):
            outcome = "no_tool_call"
        else:
            outcome = "timeout"
        result.update(outcome=outcome, detail=state.get("last_error") if outcome != "passed" else None)
    except (T3Error, OSError, ValueError, TypeError, AttributeError) as exc:
        result["detail"] = str(exc)[:256] or "execution"
    finally:
        if thread:
            try:
                state = client.status(thread, wait_s=0)
                if state.get("active_turn"):
                    client.cancel(thread)
                    client.status(thread, wait_s=10)
                client.settle(thread)
                result["settled"] = bool(client.status(thread, wait_s=10).get("settled"))
            except (T3Error, OSError, ValueError, TypeError, AttributeError):
                result["settled"] = False
        result["elapsed_s"] = round(time.monotonic() - started, 1)
    return result


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

    result = prove_route(args.route, args.wait, Bridge())
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
