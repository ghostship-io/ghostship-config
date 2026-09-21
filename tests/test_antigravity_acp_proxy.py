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
                        if message.get("method") == "initialized":
                            print(json.dumps({
                                "jsonrpc": "2.0",
                                "id": 1,
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
                ),
                text=True,
                capture_output=True,
                env=environment,
                check=True,
            )

        response = json.loads(result.stdout)
        self.assertEqual(response["result"]["methods"], ["initialize", "initialized"])
        self.assertEqual(response["result"]["initializedCount"], 1)


if __name__ == "__main__":
    unittest.main()
