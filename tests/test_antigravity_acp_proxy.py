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
    def make_launcher(self, directory: str, source: str) -> Path:
        launcher = Path(directory) / "fake-agent.py"
        launcher.write_text(f"#!{sys.executable}\n" + textwrap.dedent(source))
        launcher.chmod(0o755)
        return launcher

    def test_injects_initialized_and_suppresses_client_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            launcher = self.make_launcher(
                directory,
                """\
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
                    """,
            )
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

    def test_exits_when_agent_exits_while_client_stdin_remains_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            launcher = self.make_launcher(
                directory,
                """\
                import sys
                raise SystemExit(7)
                """,
            )
            environment = os.environ.copy()
            environment["T3CODE_ANTIGRAVITY_LAUNCHER"] = str(launcher)
            proxy = subprocess.Popen(
                [sys.executable, str(PROXY)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            self.addCleanup(lambda: proxy.kill() if proxy.poll() is None else None)
            self.assertEqual(proxy.wait(timeout=2), 7)
            assert proxy.stdin is not None
            assert proxy.stdout is not None
            assert proxy.stderr is not None
            proxy.stdin.close()
            proxy.stdout.close()
            proxy.stderr.close()


if __name__ == "__main__":
    unittest.main()
