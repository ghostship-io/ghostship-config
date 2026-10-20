"""ghostship-notify: one deduplicated publish per state, never suppressing a failed one."""
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ghostship_notify", Path(__file__).resolve().parents[1] / "modules/self-hosted/ghostship-notify.py")
notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notify)


class Ntfy(BaseHTTPRequestHandler):
    received: list = []
    status = 200

    def do_POST(self):
        Ntfy.received.append((self.headers["Authorization"], json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        self.send_response(Ntfy.status)
        self.end_headers()

    def log_message(self, *args):
        pass


class NotifyTests(unittest.TestCase):
    def test_dedupe_publishes_each_state_once_and_retries_after_a_failed_publish(self):
        server = HTTPServer(("127.0.0.1", 0), Ntfy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / "monitoring.env"
            secrets.write_text("NTFY_PUBLISH_PASSWORD='pw'\n")
            notify.SECRETS, notify.STATE_DIR = str(secrets), Path(tmp) / "state"
            os.environ["GHOSTSHIP_NOTIFY_URL"] = f"http://127.0.0.1:{server.server_port}"
            self.addCleanup(os.environ.pop, "GHOSTSHIP_NOTIFY_URL")
            base = ["--topic", "security", "--priority", "4", "--source", "sshd", "--dedupe", "k", "--title", "t"]
            Ntfy.received.clear()
            Ntfy.status = 500
            self.assertEqual(notify.main(base + ["m"]), 1)
            Ntfy.status = 200
            for argv in (base, base, base + ["--state", "resolved"]):
                self.assertEqual(notify.main(argv + ["m"]), 0)
            self.assertEqual([b["tags"][:2] for _, b in Ntfy.received],
                             [["sshd", "firing"], ["sshd", "firing"], ["sshd", "resolved"]])
            self.assertEqual(Ntfy.received[-1][1]["topic"], "security")
            self.assertTrue(Ntfy.received[-1][0].startswith("Basic "))

    def test_incident_reaches_the_coordinator_spool_even_when_ntfy_is_down(self):
        """Defect: an ntfy outage drops the repair handoff, or a resolved alert starts a repair thread."""
        server = HTTPServer(("127.0.0.1", 0), Ntfy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            secrets, spool = Path(tmp) / "monitoring.env", Path(tmp) / "incidents"
            secrets.write_text("NTFY_PUBLISH_PASSWORD='pw'\n")
            spool.mkdir()
            notify.SECRETS, notify.STATE_DIR, notify.INCIDENTS = str(secrets), Path(tmp) / "state", str(spool)
            os.environ["GHOSTSHIP_NOTIFY_URL"] = f"http://127.0.0.1:{server.server_port}"
            self.addCleanup(os.environ.pop, "GHOSTSHIP_NOTIFY_URL")
            base = ["--topic", "operations", "--source", "systemd", "--incident", "--dedupe", "x.service",
                    "--title", "Service x.service failed"]
            Ntfy.status = 500
            self.assertEqual(notify.main(base + ["exit 1"]), 1)
            Ntfy.status = 200
            self.assertEqual(notify.main(base + ["--state", "resolved", "ok"]), 0)
            (queued,) = [json.loads(path.read_text()) for path in spool.iterdir()]
            self.assertEqual((queued["key"], queued["title"], queued["message"]),
                             ("x.service", "Service x.service failed", "exit 1"))


if __name__ == "__main__":
    unittest.main()
