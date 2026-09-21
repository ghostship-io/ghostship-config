import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "packages/t3code/antigravity-acp-proxy.py"


class AntigravityAcpProxyTest(unittest.TestCase):
    def test_injects_initialized_and_suppresses_client_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / "fake-agent.py"
            launcher.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import sys

                    messages = []
                    for line in sys.stdin:
                        message = json.loads(line)
                        messages.append(message)
                        if message.get("method") == "session/new":
                            print(json.dumps({
                                "jsonrpc": "2.0",
                                "id": 1,
                                "result": {"delayedInitialize": True},
                            }), flush=True)
                            print(json.dumps({
                                "jsonrpc": "2.0",
                                "id": 2,
                                "result": {
                                    "methods": [item.get("method") for item in messages],
                                    "initializedCount": sum(
                                        item.get("method") == "initialized"
                                        for item in messages
                                    ),
                                },
                            }), flush=True)
                    """
                )
            )
            launcher.chmod(0o755)
            environment = os.environ.copy()
            environment["T3CODE_ANTIGRAVITY_LAUNCHER"] = str(launcher)
            result = subprocess.run(
                [sys.executable, str(PROXY)],
                input=(
                    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
                    '{"jsonrpc":"2.0","method":"initialized","params":{}}\n'
                    '{"jsonrpc":"2.0","id":2,"method":"session/new","params":{}}\n'
                ),
                text=True,
                capture_output=True,
                env=environment,
                check=True,
            )

        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["result"]["protocolVersion"], 1)
        self.assertEqual(responses[1]["id"], 2)
        self.assertEqual(
            responses[1]["result"]["methods"],
            ["initialize", "initialized", "session/new"],
        )
        self.assertEqual(responses[1]["result"]["initializedCount"], 1)


if __name__ == "__main__":
    unittest.main()
