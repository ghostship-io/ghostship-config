"""Probe the built container's ACP protocol without credentials or network."""

import json
import os
import platform
import pwd
import queue
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# The harness sandboxes tool execution as this account. Its absence crashes the
# agent inside session creation instead of failing at protocol initialization.
SANDBOX_USER = "nobody"
# ELF e_machine values. The ACP server is emulated on 16 KiB-page hosts, but the
# harness must match the host CPU: emulating its Go runtime panics mid-turn.
ELF_MACHINE = {"x86_64": 62, "aarch64": 183, "arm64": 183}


def elf_machine(path):
    with Path(path).open("rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return None
    return struct.unpack_from("<H", header, 18)[0]


def harness_binary():
    """Resolve the harness binary the ACP wrapper will actually execute.

    Mirrors the package wrapper: a staged runtime harness is used only when it
    is already native to this host; otherwise the bundled native binary wins.
    """
    expected = ELF_MACHINE.get(platform.machine())
    wrapper = Path("/bin/localharness_external").resolve()
    # The package installs its fallback at <out>/libexec, next to <out>/bin.
    bundled = wrapper.parent.parent / "libexec" / "localharness_external"
    runtime = os.environ.get("T3CODE_ANTIGRAVITY_RUNTIME")
    if runtime:
        staged = Path(runtime) / "localharness_external"
        if staged.exists() and elf_machine(staged) == expected:
            return staged
    return bundled if bundled.exists() else wrapper


def main():
    # The harness drops privileges to this account for sandboxed tool work. A
    # container image without it aborts the session once the agent acts.
    try:
        pwd.getpwnam(SANDBOX_USER)
    except KeyError:
        raise RuntimeError(f"ACP sandbox account '{SANDBOX_USER}' is missing")
    expected = ELF_MACHINE.get(platform.machine())
    harness = harness_binary()
    actual = elf_machine(harness)
    if expected is not None and actual is not None and actual != expected:
        raise RuntimeError(
            f"ACP harness {harness} is not native to {platform.machine()} "
            f"(e_machine {actual}); emulating it crashes long turns"
        )
    # Always invoke the wrapper so the x86_64 server is emulated on ARM64 hosts
    # and the staged runtime under T3CODE_ANTIGRAVITY_RUNTIME is honored.
    server = "/bin/agy_acp_server.par"
    with tempfile.TemporaryDirectory(prefix="t3code-acp-") as directory:
        env = dict(
            os.environ,
            HOME=directory,
            GEMINI_HOME=directory,
            XDG_CONFIG_HOME=f"{directory}/config",
            XDG_DATA_HOME=f"{directory}/data",
            XDG_STATE_HOME=f"{directory}/state",
            AGY_ACP_FORCE_FILE_STORAGE="1",
        )
        log = Path(directory) / "stderr.log"
        with log.open("w") as stderr:
            proc = subprocess.Popen(
                [str(server), "--uid="],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
            )
            replies = queue.Queue()

            def read_replies():
                for output_line in proc.stdout:
                    replies.put(output_line)
                replies.put(None)

            output_thread = threading.Thread(target=read_replies, daemon=True)
            output_thread.start()

            def wait_for_reply(request_id, label):
                deadline = time.monotonic() + 45
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError(f"ACP {label} timed out")
                    try:
                        line = replies.get(timeout=remaining)
                    except queue.Empty as error:
                        raise RuntimeError(f"ACP {label} timed out") from error
                    if line is None:
                        raise RuntimeError(f"ACP exited before {label}")
                    reply = json.loads(line)
                    if reply.get("id") == request_id:
                        return reply

            try:
                request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientCapabilities": {},
                        "clientInfo": {"name": "container-smoke", "version": "1"},
                    },
                }
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
                reply = wait_for_reply(1, "initialization")
                result = reply.get("result", {})
                if result.get("protocolVersion") != 1 or not any(
                    method.get("id") == "oauth-personal"
                    for method in result.get("authMethods", [])
                ):
                    raise RuntimeError(f"Unexpected ACP response: {reply}")

                # The compatibility proxy synthesizes initialize so T3 is not
                # blocked by Antigravity's delayed reply. Exercise an advertised
                # method as well, proving the staged agent itself is alive and
                # processing requests before an updater publishes it.
                request = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "session/list",
                    "params": {},
                }
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
                reply = wait_for_reply(2, "session/list response")
                if ("result" in reply) == ("error" in reply):
                    raise RuntimeError(f"Unexpected ACP session/list response: {reply}")
                print(
                    "ACP initialization and session/list round trip passed:",
                    result.get("agentInfo", {}),
                )
            except Exception:
                stderr.flush()
                print(log.read_text()[-4000:])
                raise
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    main()
