"""Probe the built container's ACP protocol without credentials or network."""

import json
import os
import select
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix="t3code-acp-") as directory:
        env = dict(
            os.environ,
            HOME=directory,
            GEMINI_HOME=directory,
            XDG_CONFIG_HOME=f"{directory}/config",
            XDG_DATA_HOME=f"{directory}/data",
            XDG_STATE_HOME=f"{directory}/state",
            AGY_ACP_FORCE_FILE_STORAGE="1",
            ANTIGRAVITY_HARNESS_PATH="/bin/localharness_external",
        )
        log = Path(directory) / "stderr.log"
        with log.open("w") as stderr:
            proc = subprocess.Popen(
                ["/bin/agy_acp_server.par", "--uid="],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
            )
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
                deadline = time.monotonic() + 45
                while True:
                    remaining = deadline - time.monotonic()
                    if (
                        remaining <= 0
                        or not select.select([proc.stdout], [], [], remaining)[0]
                    ):
                        raise RuntimeError("ACP initialization timed out")
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("ACP exited before initialization")
                    reply = json.loads(line)
                    if reply.get("id") == 1:
                        break
                result = reply.get("result", {})
                if result.get("protocolVersion") != 1 or not any(
                    method.get("id") == "oauth-personal"
                    for method in result.get("authMethods", [])
                ):
                    raise RuntimeError(f"Unexpected ACP response: {reply}")
                print("ACP initialization passed:", result.get("agentInfo", {}))
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
