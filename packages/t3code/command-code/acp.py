#!/usr/bin/env python3
"""Policy boundary around Command Code's native ACP server, never a model adapter."""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_POLICY = json.loads((ROOT / "paid-models.json").read_text())
PAID = frozenset(MODEL_POLICY["models"])
DEFAULT = MODEL_POLICY["default"]


def provider_environment(environment):
    # Use only native login in the persistent HOME. Discard externally injected
    # Command Code credential overrides and unrelated vault process variables.
    env = {k: v for k, v in environment.items()
           if not k.startswith(("BW_", "COMMAND_CODE_", "AGENT_BW_"))}
    env.update(CMD_ZDR="1", COMMANDCODE_SKIP_UPDATES="1",
               CMD_DISABLE_REMOTE_MODEL_CATALOG="1", DO_NOT_TRACK="1")
    return env


class Policy:
    def __init__(self):
        self.pending = {}
        self.sessions = {}

    def request(self, message):
        method = message.get("method")
        if not method:  # Client replies to native permission/MCP requests.
            return
        params = message.get("params", {})
        if method not in {"initialize", "session/new", "session/prompt", "session/cancel",
                          "session/set_model", "session/set_config_option", "session/set_mode",
                          "session/close"}:
            raise ValueError("method unavailable on the paid ZDR route")
        if method == "session/set_model" and params.get("modelId") not in PAID:
            raise ValueError("model is not in the reviewed paid GOAT allowlist")
        if method == "session/set_config_option":
            if params.get("configId") == "model":
                if params.get("value") not in PAID:
                    raise ValueError("model is not in the reviewed paid GOAT allowlist")
            elif params.get("configId") != "effort":
                raise ValueError("configuration option unavailable on the paid ZDR route")
        if method == "session/prompt":
            if self.sessions.get(params.get("sessionId")) not in PAID:
                raise ValueError("select a reviewed paid GOAT model before prompting")
            if any(b.get("type") == "text" and b.get("text", "").lstrip().startswith("/")
                   for b in params.get("prompt", [])):
                raise ValueError("slash commands are disabled; use the ACP model and mode controls")
        if "id" in message:
            self.pending[message["id"]] = (method, params)

    def catalog(self, result, session, *, initial=False):
        selected = self.sessions.get(session)
        models = result.get("models")
        if models:
            models["availableModels"] = [m for m in models.get("availableModels", [])
                                         if m.get("modelId") in PAID]
            models["availableModels"].sort(key=lambda m: m["modelId"] != DEFAULT)
            selected = models.get("currentModelId")
            if selected not in PAID and not initial:
                raise ValueError("native agent selected an unapproved model")
        for option in result.get("configOptions", []):
            if option.get("category") == "model" or option.get("id") == "model":
                option["options"] = [m for m in option.get("options", []) if m.get("value") in PAID]
                option["options"].sort(key=lambda m: m["value"] != DEFAULT)
                selected = option.get("currentValue")
                if selected not in PAID and not initial:
                    raise ValueError("native agent selected an unapproved model")
        # An unapproved native default must not prevent session creation. Keep
        # its reported value honest; no prompt crosses until a paid pick is ACKed.
        self.sessions[session] = selected if selected in PAID else None

    def response(self, message):
        request = self.pending.pop(message.get("id"), None) if "method" not in message else None
        if request and "result" in message:
            method, params = request
            result = message["result"]
            if method == "initialize":
                caps = result.get("agentCapabilities", {})
                caps["loadSession"] = False
                caps["sessionCapabilities"] = {"close": {}}
            elif method == "session/new":
                self.catalog(result, result["sessionId"], initial=True)
                return result["sessionId"]
            elif method in {"session/set_model", "session/set_config_option"}:
                session = params.get("sessionId")
                if method == "session/set_model":
                    self.sessions[session] = params["modelId"]
                self.catalog(result, session)
        if message.get("method") == "session/update":
            params = message.get("params", {})
            update = params.get("update", {})
            session = params.get("sessionId")
            if update.get("sessionUpdate") == "current_model_update":
                self.sessions[session] = update.get("currentModelId")
                if self.sessions[session] not in PAID:
                    raise ValueError("native agent selected an unapproved model")
            if update.get("sessionUpdate") == "config_option_update":
                self.catalog(update, session)
            if update.get("sessionUpdate") == "available_commands_update":
                update["availableCommands"] = []


async def serve(env):
    process = await asyncio.create_subprocess_exec(
        "node", str(ROOT / "node_modules/command-code/dist/index.mjs"), "acp",
        env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        limit=16 * 1024 * 1024,
        # Native diagnostics can contain project data; keep them out of T3 logs.
        stderr=asyncio.subprocess.DEVNULL,
    )
    policy = Policy()
    defaults = {}
    initializing = {}
    write_lock = asyncio.Lock()

    async def emit(message):
        async with write_lock:
            sys.stdout.write(json.dumps(message) + "\n")
            sys.stdout.flush()

    async def client():
        reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
        await asyncio.get_running_loop().connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        while line := await reader.readline():
            message = json.loads(line)
            try:
                policy.request(message)
            except ValueError as error:
                if "id" in message:
                    await emit({"jsonrpc": "2.0", "id": message["id"],
                                "error": {"code": -32602, "message": str(error)}})
                continue
            process.stdin.write(json.dumps(message).encode() + b"\n")
            await process.stdin.drain()

    async def agent():
        while line := await process.stdout.readline():
            message = json.loads(line)
            if (message.get("method") == "session/update" and
                    message.get("params", {}).get("sessionId") in initializing):
                policy.response(message)
                initializing[message["params"]["sessionId"]].append(message)
                continue
            pending_default = defaults.pop(message.get("id"), None) if "method" not in message else None
            if pending_default:
                original, session = pending_default
                if "result" in message:
                    # Acknowledge the default only after the native agent does.
                    result = original["result"]
                    if result.get("models"):
                        result["models"]["currentModelId"] = DEFAULT
                    for option in result.get("configOptions", []):
                        if option.get("category") == "model" or option.get("id") == "model":
                            option["currentValue"] = DEFAULT
                    policy.sessions[session] = DEFAULT
                    policy.catalog(result, session)
                else:
                    # A failed default selection still permits session creation.
                    # Prompts wait for the client's explicit paid selection.
                    policy.sessions[session] = None
                await emit(original)
                for update in initializing.pop(session, []):
                    await emit(update)
                continue
            session = policy.response(message)
            if session:
                policy.sessions[session] = None
                identifier = "paid-default-" + uuid.uuid4().hex
                defaults[identifier] = (message, session)
                initializing[session] = []
                process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identifier,
                    "method": "session/set_model", "params": {"sessionId": session, "modelId": DEFAULT}}).encode() + b"\n")
                await process.stdin.drain()
                continue
            await emit(message)

    tasks = [asyncio.create_task(client()), asyncio.create_task(agent())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        if process.returncode is None:
            process.terminate()
        await process.wait()


def main():
    env = provider_environment(os.environ)
    if sys.argv[1:] in (["login"], ["--version"]):
        # Native login owns its browser/device flow and auth.json. Do not read,
        # copy or serialize that token; HOME is the persisted T3 user home.
        os.execvpe("node", ["node", str(ROOT / "node_modules/command-code/dist/index.mjs"),
                           *sys.argv[1:]], env)
    if sys.argv[1:] != ["acp"]:
        raise ValueError("this managed cmd entry accepts acp, login or --version")
    asyncio.run(serve(env))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Command Code paid ZDR provider unavailable; check native login and policy.", file=sys.stderr)
        sys.exit(1)
