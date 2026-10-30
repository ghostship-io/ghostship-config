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


def standard_options(client, instance, model):
    """Use only supported non-fast options from the live native catalog."""
    providers = client.capabilities(instance).get("providers", [])
    matches = [(provider, item) for provider in providers if provider.get("providerInstanceId") == instance
               for item in provider.get("models", []) if item.get("id") == model]
    if len(matches) != 1 or matches[0][0].get("available") is not True:
        raise ValueError("native route is not currently available")
    descriptors = {item.get("id"): item for item in matches[0][1].get("options", []) if isinstance(item, dict)}
    options = {}
    tier = descriptors.get("serviceTier")
    if instance == "codex" and not tier:
        raise ValueError("standard Codex tier is not verifiable")
    if tier:
        values = tier.get("values")
        if tier.get("type") == "boolean" or (values is not None and "standard" not in values):
            raise ValueError("standard tier is not supported")
        options["serviceTier"] = "standard"
    fast = descriptors.get("fastMode")
    if fast:
        if fast.get("type") != "boolean":
            raise ValueError("fast mode cannot be disabled")
        options["fastMode"] = False
    return options


def native_is_admitted(policy, instance, model):
    if not isinstance(policy, dict) or policy.get("schema") != "ghostship.route-policy/v2":
        return False
    providers, routes = policy.get("providers"), policy.get("routes")
    if not isinstance(providers, dict) or not isinstance(routes, list):
        return False
    admitted = []
    for row in routes:
        if not isinstance(row, dict) or not isinstance(row.get("roles"), list):
            continue
        provider = row.get("provider")
        provider_policy = providers.get(provider) if isinstance(provider, str) else None
        if (row.get("admit") is True and "worker" in row["roles"]
                and row.get("provider_instance") == instance and row.get("model") == model
                and isinstance(provider_policy, dict) and provider_policy.get("admit") is True
                and row.get("billing") in ("subscription", "free", "promotion")):
            admitted.append(row)
    return len(admitted) == 1


def prove_route(route, wait, client, native_target=None):
    from ghostship_t3.bridge import T3Error
    from ghostship_t3.models import read_document, _selection

    provider, sep, model = route.partition("/")
    if not sep or not provider or not model:
        raise T3Error("route must be provider/model")
    target = native_target
    if target is None:
        document = read_document()
        selected = _selection(document, time.time())
        for row in selected.get("worker") or []:
            native = row.get("native") or {}
            if row.get("provider") == provider and row.get("model") == model and native.get("instanceId") and native.get("model"):
                target = (native["instanceId"], native["model"],
                          {item["id"]: item["value"] for item in native.get("options") or []
                           if isinstance(item, dict) and item.get("id")})
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
    parser.add_argument("--instance")
    parser.add_argument("--native-model")
    parser.add_argument("--options-json", default="{}")
    args = parser.parse_args()

    agent_tools = (os.environ.get("GHOSTSHIP_TOOLS_ROOT")
                   or os.environ.get("GHOSTSHIP_AGENT_ROOT"))
    if not agent_tools:
        parser.error("candidate agent tools path is unavailable")
    sys.path.insert(0, str(Path(agent_tools) / "tools/python"))

    from ghostship_t3.bridge import Bridge, T3Error

    native_target = None
    if args.instance or args.native_model:
        if not args.instance or not args.native_model:
            parser.error("both native identity fields are required")
        try:
            policy = json.loads(Path("/etc/ghostship/route-policy.json").read_text())
            options = json.loads(args.options_json)
            if not native_is_admitted(policy, args.instance, args.native_model):
                raise ValueError("native route is not admitted")
            if not isinstance(options, dict) or any(k not in ("serviceTier", "fastMode") for k in options):
                raise ValueError("invalid native options")
            if options.get("serviceTier", "standard") != "standard" or options.get("fastMode", False) is not False:
                raise ValueError("priority or fast mode is not permitted")
            if args.instance == "codex" and options != {"serviceTier": "standard", "fastMode": False}:
                raise ValueError("Codex requires standard tier and fast mode off")
        except (OSError, ValueError, TypeError, AttributeError):
            parser.error("native route admission or standard tier could not be verified")
        native_target = (args.instance, args.native_model, options)
    client = Bridge()
    if native_target:
        try:
            safe_options = standard_options(client, native_target[0], native_target[1])
            native_target = (native_target[0], native_target[1], safe_options)
        except (ValueError, TypeError, KeyError, OSError, T3Error):
            print(json.dumps({"outcome": "route_unavailable", "settled": True,
                              "error": {"code": "route-unavailable"}}, sort_keys=True))
            return 1
    result = prove_route(args.route, args.wait, client, native_target)
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
