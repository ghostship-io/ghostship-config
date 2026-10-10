import http.client
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest


CONFIG = Path(__file__).resolve().parents[1] / "modules/self-hosted/homepage-podman-broker.conf"


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=5)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append(self.path)
        body = b'[{"Id":"example","State":"running"}]'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("nginx"), "nginx is required for broker integration tests")
class Broker(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream_path = self.root / "upstream.sock"
        self.upstream = socketserver.UnixStreamServer(str(self.upstream_path), Upstream)
        self.upstream.requests = []
        thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)
        rendered = CONFIG.read_text().replace("/run/homepage-podman-broker", str(self.root))
        rendered = rendered.replace("/run/podman/podman.sock", str(self.upstream_path))
        config = self.root / "nginx.conf"
        config.write_text(rendered)
        self.broker = subprocess.Popen(
            ["nginx", "-e", "stderr", "-p", str(self.root), "-c", str(config)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        self.addCleanup(self.stop_broker)
        self.socket = self.root / "podman.sock"
        for _ in range(100):
            if self.socket.exists():
                break
            if self.broker.poll() is not None:
                self.fail(self.broker.stderr.read().decode())
            time.sleep(0.02)
        else:
            self.fail("broker did not create its Unix socket")

    def stop_broker(self):
        self.broker.terminate()
        self.broker.communicate(timeout=5)

    def request(self, method, path):
        connection = UnixHTTPConnection(self.socket)
        connection.request(method, path)
        response = connection.getresponse()
        result = (response.status, response.read())
        connection.close()
        return result

    def test_dashboard_list_filters_and_single_snapshot_stats_reach_upstream(self):
        for path in ["/containers/json?all=true", "/v1.41/containers/json?filters=%7B%7D",
                     "/v1.41/containers/example/stats?stream=false", "/_ping", "/version"]:
            with self.subTest(path=path):
                status, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertIn(b'"State":"running"', body)
                self.assertIn(path, self.upstream.requests)

    def test_control_secret_file_and_streaming_routes_never_reach_upstream(self):
        cases = [(method, "/containers/json") for method in ["POST", "PUT", "PATCH", "DELETE"]]
        cases += [("GET", path) for path in [
            "/containers/example/json", "/containers/example/archive?path=/run/secrets",
            "/containers/example/logs", "/containers/example/exec", "/libpod/containers/json",
            "/v1.41/containers/example/stats", "/containers/example/stats?stream=true",
            "/containers/example/stats?stream=false&stream=true",
        ]]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                status, _ = self.request(method, path)
                self.assertEqual(status, 403)
        self.assertEqual(self.upstream.requests, [])


if __name__ == "__main__":
    unittest.main()
