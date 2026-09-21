#!/usr/bin/env python3
"""Bridge Antigravity's out-of-order ACP initialization handshake."""

import json
import os
import subprocess
import sys
import threading


def is_method(line: bytes, method: str) -> bool:
    try:
        return json.loads(line).get("method") == method
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
        return False


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

    def forward_output() -> None:
        try:
            while chunk := child.stdout.read(65536):
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
        except (BrokenPipeError, OSError) as error:
            output_error.append(error)

    output_thread = threading.Thread(target=forward_output, daemon=True)
    output_thread.start()
    injected_initialized = False
    suppressed_client_initialized = False

    try:
        for line in sys.stdin.buffer:
            if (
                injected_initialized
                and not suppressed_client_initialized
                and is_method(line, "initialized")
            ):
                suppressed_client_initialized = True
                continue

            child.stdin.write(line)
            child.stdin.flush()
            if not injected_initialized and is_method(line, "initialize"):
                child.stdin.write(
                    b'{"jsonrpc":"2.0","method":"initialized","params":{}}\n'
                )
                child.stdin.flush()
                injected_initialized = True
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            child.stdin.close()
        except OSError:
            pass

    status = child.wait()
    output_thread.join(timeout=2)
    if output_error and status == 0:
        return 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
