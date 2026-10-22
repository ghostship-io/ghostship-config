"""The T3 Code transport: the bearer never crosses a plain socket, and a
failure never carries a provider message out of the process."""
import importlib.util
import json
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ai_usage_t3client", ROOT / "t3client.py")
t3client = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_t3client"] = t3client
spec.loader.exec_module(t3client)

try:
    from websockets.sync.server import serve
    from websockets.exceptions import ConnectionClosed
except ImportError:  # pragma: no cover - the CI shell ships the library
    serve = None
    ConnectionClosed = Exception

SECRET = "sk-live-do-not-leak@example.com"


class Server:
    """A local T3 Code stand-in."""

    def __init__(self, handler):
        self.handler = handler
        self.server = None
        self.thread = None

    def __enter__(self):
        if serve is None:
            raise unittest.SkipTest("the websockets library is not installed")
        self.server = serve(self.handler, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        if self.server is not None:
            self.server.shutdown()
            self.server.socket.close()

    @property
    def url(self):
        port = self.server.socket.getsockname()[1]
        return f"http://127.0.0.1:{port}"


def echo_handler(connection):
    for raw in connection:
        request = json.loads(raw)
        if request.get("tag") == "server.explode":
            connection.send(
                json.dumps(
                    {
                        "_tag": "Exit",
                        "requestId": request.get("id"),
                        "exit": {
                            "_tag": "Failure",
                            "cause": [{"_tag": "Fail", "error": {"detail": SECRET}}],
                        },
                    }
                )
            )
            continue
        connection.send(
            json.dumps(
                {
                    "_tag": "Exit",
                    "requestId": request.get("id"),
                    "exit": {"_tag": "Success", "value": {"echo": request.get("payload")}},
                }
            )
        )


def huge_handler(connection):
    for _raw in connection:
        connection.send(b"x" * (9 * 1024 * 1024))


class TransportTests(unittest.TestCase):
    def test_the_socket_url_is_derived_from_the_endpoint(self):
        client = t3client.T3Client("http://10.89.0.225:3773", "token")
        self.assertEqual(
            client.socket_url(), "ws://10.89.0.225:3773/ws?orchestrationProtocol=2"
        )
        secure = t3client.T3Client("https://t3code.ghostship.io", "token")
        self.assertEqual(
            secure.socket_url(), "wss://t3code.ghostship.io/ws?orchestrationProtocol=2"
        )

    def test_an_https_endpoint_is_never_reached_over_a_plain_socket(self):
        captured = {}

        class FakeConnection:
            def send(self, _message):
                return None

            def recv(self, timeout=None):
                return json.dumps(
                    {"_tag": "Exit", "requestId": 1, "exit": {"_tag": "Success", "value": {}}}
                )

            def close(self):
                return None

        def fake_connect(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeConnection()

        original = t3client._websocket_connect
        t3client._websocket_connect = fake_connect
        try:
            client = t3client.T3Client("https://t3code.ghostship.io", "token")
            with client:
                client.call("server.getConfig", {})
        finally:
            t3client._websocket_connect = original
        self.assertTrue(captured["url"].startswith("wss://"))
        self.assertIsNotNone(captured.get("ssl"))
        self.assertTrue(captured["ssl"].verify_mode)
        self.assertTrue(captured["ssl"].check_hostname)
        self.assertEqual(
            captured["additional_headers"]["Authorization"], "Bearer token"
        )
        # The frame and queue bounds are set, so a large or fast peer cannot
        # grow the collector without limit.
        self.assertLessEqual(captured["max_size"], t3client.MAX_MESSAGE_BYTES)
        self.assertLessEqual(captured["max_queue"], 64)

    def test_a_read_call_returns_the_value(self):
        with Server(echo_handler) as server:
            client = t3client.T3Client(server.url, "token", timeout=10)
            with client:
                value = client.call("server.getConfig", {"a": 1})
        self.assertEqual(value, {"echo": {"a": 1}})

    def test_a_provider_message_never_leaves_the_process(self):
        with Server(echo_handler) as server:
            client = t3client.T3Client(server.url, "token", timeout=10)
            with client:
                with self.assertRaises(t3client.T3Error) as raised:
                    client.call("server.explode", {})
        self.assertNotIn(SECRET, str(raised.exception))
        self.assertIn(raised.exception.reason, {"rpc_failed", "protocol_error"})

    def test_an_oversized_message_is_refused(self):
        with Server(huge_handler) as server:
            client = t3client.T3Client(server.url, "token", timeout=10)
            with client:
                with self.assertRaises(t3client.T3Error) as raised:
                    client.call("server.getConfig", {})
        self.assertNotIn(SECRET, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
