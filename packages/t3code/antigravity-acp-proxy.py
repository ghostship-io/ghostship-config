#!/usr/bin/env python3
"""Bridge Antigravity's out-of-order ACP initialization handshake."""

import json
import os
import select
import subprocess
import sys
import threading


def decode_message(line: bytes) -> dict[str, object] | None:
    try:
        value = json.loads(line)
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def initialize_response(request_id: object) -> bytes:
    version = os.environ.get("T3CODE_ANTIGRAVITY_VERSION", "1.1.1")
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": 1,
                    "agentCapabilities": {
                        "loadSession": True,
                        "promptCapabilities": {
                            "image": True,
                            "audio": True,
                            "embeddedContext": True,
                        },
                        "mcpCapabilities": {"http": True, "sse": True},
                        "sessionCapabilities": {"list": {}, "resume": {}},
                        "auth": {"logout": {}},
                    },
                    "authMethods": [
                        {
                            "id": "oauth-personal",
                            "name": "Log in with Google",
                            "description": "Log in with your Google account",
                        },
                        {
                            "id": "oauth-business",
                            "name": "Log in with Gemini Enterprise",
                            "description": "Log in with Gemini Enterprise",
                        },
                        {
                            "id": "gemini-api-key",
                            "name": "Gemini API key",
                            "description": "Use a Gemini Developer API key",
                        },
                        {
                            "id": "agent-platform",
                            "name": "Gemini Enterprise Agent Platform",
                            "description": "Use Gemini Enterprise Agent Platform",
                        },
                    ],
                    "agentInfo": {
                        "name": "antigravity-acp",
                        "title": "Google Antigravity",
                        "version": f"agy_acp_server_{version}",
                    },
                },
            },
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def main() -> int:
    launcher = os.environ["T3CODE_ANTIGRAVITY_LAUNCHER"]
    child = subprocess.Popen(
        [launcher, *sys.argv[1:]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
    )
    assert child.stdin is not None
    assert child.stdout is not None

    output_error: list[BaseException] = []
    suppressed_response_ids: set[object] = set()
    suppression_lock = threading.Lock()
    child_exited = threading.Event()

    def forward_output() -> None:
        try:
            for line in child.stdout:
                message = decode_message(line)
                with suppression_lock:
                    suppress = (
                        message is not None
                        and message.get("id") in suppressed_response_ids
                    )
                    if suppress:
                        suppressed_response_ids.remove(message.get("id"))
                if suppress:
                    continue
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
        except (BrokenPipeError, OSError) as error:
            output_error.append(error)

    def forward_input() -> None:
        injected_initialized = False
        suppressed_client_initialized = False

        def forward_line(line: bytes) -> None:
            nonlocal injected_initialized, suppressed_client_initialized
            message = decode_message(line)
            if (
                injected_initialized
                and not suppressed_client_initialized
                and message is not None
                and message.get("method") == "initialized"
            ):
                suppressed_client_initialized = True
                return

            initialize_id = None
            if message is not None and message.get("method") == "initialize":
                initialize_id = message.get("id")
                with suppression_lock:
                    suppressed_response_ids.add(initialize_id)

            child.stdin.write(line)
            child.stdin.flush()
            if not injected_initialized and initialize_id is not None:
                child.stdin.write(
                    b'{"jsonrpc":"2.0","method":"initialized","params":{}}\n'
                )
                child.stdin.flush()
                injected_initialized = True
                sys.stdout.buffer.write(initialize_response(initialize_id))
                sys.stdout.buffer.flush()

        pending = b""
        try:
            while not child_exited.is_set():
                readable, _, _ = select.select([sys.stdin.buffer], [], [], 0.1)
                if not readable:
                    continue
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    if pending:
                        forward_line(pending)
                    break
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    forward_line(line + b"\n")
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    output_thread = threading.Thread(target=forward_output, daemon=True)
    input_thread = threading.Thread(target=forward_input, daemon=True)
    output_thread.start()
    input_thread.start()

    status = child.wait()
    child_exited.set()
    input_thread.join(timeout=1)
    try:
        child.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    output_thread.join(timeout=2)
    if output_error and status == 0:
        return 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
