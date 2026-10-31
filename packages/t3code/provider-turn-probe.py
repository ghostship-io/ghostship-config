#!/usr/bin/env python3
"""Run the real approved-route tool-loop proof in an explicit candidate workspace."""

import argparse
import json
import os
import re
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


TOOL_ITEM_TYPES = frozenset({"dynamic_tool", "command_execution", "file_change",
                             "web_search", "image_view"})


def _completed_tool_item(item):
    """A real completed tool item from the T3 v0.1.5 projection.

    T3 emits dynamic_tool/command_execution/file_change/web_search/image_view
    (session-logic-D8bgEKqg.js, baked app 0.1.5). ``command_execution`` also
    carries the pre-run workspace preparation; that is not a model tool call.
    """
    kind = item.get("type")
    if kind == "tool_result":
        return item.get("ok") is True and item.get("status") in (None, "completed")
    if kind not in TOOL_ITEM_TYPES or item.get("status") != "completed":
        return False
    if kind == "command_execution" and (
            item.get("title") == "Workspace ready" or item.get("input") == "Preparing workspace"):
        return False
    return True


def has_tool_result(client, thread):
    projection = (client._get(f"/api/orchestration/threads/{quote(thread, safe='')}") or {}).get("projection") or {}
    runs = projection.get("runs") or []
    if len(runs) != 1 or not isinstance(runs[0], dict) or not runs[0].get("id"):
        return False
    run_id = runs[0]["id"]
    items = [item for item in projection.get("turnItems") or []
             if isinstance(item, dict) and item.get("runId") == run_id]
    return any(_completed_tool_item(item) for item in items)


def standard_options(client, instance, model, requested=None):
    """Use only supported non-fast options from the live native catalog.

    ``requested`` carries the approved effort/option from the route policy. It
    is validated against the native descriptor rather than overwritten, so the
    real turn uses the same effort as the worker route.
    """
    providers = client.capabilities(instance).get("providers", [])
    matches = [(provider, item) for provider in providers if provider.get("providerInstanceId") == instance
               for item in provider.get("models", []) if item.get("id") == model]
    if len(matches) != 1:
        raise ValueError("native route is not currently available")
    provider = matches[0][0]
    if provider.get("available") is not True:
        if (provider.get("authReady") is False
                or str(provider.get("authStatus") or "").lower() == "unauthenticated"):
            raise ValueError("native route is not authenticated")
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
    requested = requested or {}
    if not isinstance(requested, dict):
        raise ValueError("invalid native options")
    if requested.get("serviceTier", "standard") != "standard":
        raise ValueError("priority or fast mode is not permitted")
    if requested.get("fastMode", False) is not False:
        raise ValueError("priority or fast mode is not permitted")
    for key, value in requested.items():
        if key in ("serviceTier", "fastMode"):
            continue
        descriptor = descriptors.get(key)
        if descriptor is None:
            raise ValueError(f"option {key!r} is not available")
        allowed = descriptor.get("values")
        if descriptor.get("type") == "boolean":
            valid = isinstance(value, bool)
        else:
            valid = isinstance(value, str) and (allowed is None or value in allowed)
        if not valid:
            raise ValueError(f"option {key!r} is not supported")
        options[key] = value
    return options


def probe_error_kind(error):
    """A bounded class for a pre-launch probe failure; never echoes the message."""
    message = str(error).lower()
    if "no t3 provider instance" in message:
        return "provider-instance-missing"
    if "session token" in message:
        return "t3-auth"
    if "unreachable" in message:
        return "t3-unreachable"
    if "native route is not authenticated" in message:
        return "provider-auth"
    if "native route is not currently available" in message:
        return "route-not-available"
    if "option " in message and ("not available" in message or "not supported" in message):
        return "option-invalid"
    return "probe-error"


def failure_kind(result):
    """Classify a prove_route failure without echoing provider text."""
    detail = str(result.get("detail") or "").lower()
    if re.search(r"\b(?:auth|authentication|unauthorized|forbidden|401|403)\b", detail):
        return "provider-auth"
    if "model unavailable" in detail or "model-unavailable" in detail:
        return "model-unavailable"
    if "quota" in detail or "rate limit" in detail or "429" in detail:
        return "quota"
    outcome = str(result.get("outcome") or "").lower().replace("_", "-")
    if outcome in ("execution", "timeout", "provider-schema", "invalid-request",
                   "no-tool-call", "wrong-tool-result"):
        return outcome
    return "provider-error"


def route_unavailable_output(instance, model, kind):
    """The structured failure the acceptance record can retain safely."""
    return {"outcome": "route_unavailable", "settled": True,
            "error": {"code": "route-unavailable", "kind": kind,
                      "instance": instance, "model": model}}


def acceptance_route_allows(route, instance, model):
    """The acceptance route is the single admission authority.

    Candidate acceptance has already admitted this exact route; the probe only
    checks that the route object it was handed names the requested target.
    """
    return (isinstance(route, dict)
            and route.get("acceptance_only") is True
            and route.get("billing") == "free"
            and route.get("provider") == "opencode-free"
            and (route.get("provider_instance"), route.get("model")) == (instance, model))


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
    parser.add_argument("--acceptance-route-json")
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
            options = json.loads(args.options_json)
            acceptance_route = json.loads(args.acceptance_route_json) if args.acceptance_route_json else None
            if not acceptance_route_allows(acceptance_route, args.instance, args.native_model):
                raise ValueError("acceptance route does not admit the native target")
            allowed = ("serviceTier", "fastMode", "variant")
            if (not isinstance(options, dict) or any(k not in allowed for k in options)
                    or ("variant" in options and not isinstance(options["variant"], str))):
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
            safe_options = standard_options(client, native_target[0], native_target[1], options)
            native_target = (native_target[0], native_target[1], safe_options)
        except (ValueError, TypeError, KeyError, OSError, T3Error) as error:
            print(json.dumps(route_unavailable_output(
                native_target[0], native_target[1], probe_error_kind(error)), sort_keys=True))
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
        output["error"] = {"code": safe_failure_code(result),
                           "kind": failure_kind(result)}
    print(json.dumps(output, sort_keys=True))
    return 0 if result.get("outcome") == "passed" and result.get("settled") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
