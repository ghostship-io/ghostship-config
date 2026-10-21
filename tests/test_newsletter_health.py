"""Newsletter monitor -> real notifier -> isolated incident spool and fake ntfy."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "modules/self-hosted/newsletter-health.py"
spec = importlib.util.spec_from_file_location("newsletter_health", SCRIPT)
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class HealthTests(unittest.TestCase):
    def test_unavailable_stale_or_inconsistent_monitor_cannot_report_success(self):
        now = datetime(2026, 10, 21, 20, tzinfo=timezone.utc)
        report = {"checked_at": now.isoformat(), "issue_date": "2026-10-21", "healthy": True,
                  "unhealthy_reasons": [], "last_due_delivery": {"status": "current"}}
        result = subprocess.CompletedProcess([], 0, json.dumps(report))
        with mock.patch.object(health.subprocess, "run", return_value=result):
            self.assertEqual(health.observe(["monitor"], now), "")
            for changes in ({"checked_at": "2026-10-20T20:00:00+00:00"},
                            {"issue_date": "2026-10-20"}, {"healthy": False},
                            {"last_due_delivery": None},
                            {"last_due_delivery": {"status": "missing"}},
                            {"unhealthy_reasons": ["untrusted log text"]}):
                result.stdout = json.dumps(report | changes)
                self.assertEqual(health.observe(["monitor"], now), "monitor_unavailable")
            result.stdout = "{}"
            self.assertEqual(health.observe(["monitor"], now), "monitor_unavailable")
        with mock.patch.object(health.subprocess, "run", side_effect=subprocess.TimeoutExpired("monitor", 180)):
            self.assertEqual(health.observe(["monitor"], now), "monitor_unavailable")

    def test_failure_retry_recurrence_and_resolution_use_only_fake_boundaries(self):
        messages = []
        available = [True]

        class Ntfy(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if available[0]:
                    messages.append(payload)
                self.send_response(200 if available[0] else 503)
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Ntfy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spool = root / "incidents"
            spool.mkdir()
            secrets = root / "monitoring.env"
            secrets.write_text("NTFY_PUBLISH_PASSWORD=fake-test-password\n")
            report = root / "report.json"
            monitor = root / "monitor.py"
            monitor.write_text("import json,sys\np=json.load(open(sys.argv[1]))\n"
                               "print(json.dumps(p))\nsys.exit(0 if p['healthy'] else 4)\n")
            notify = root / "notify"
            notify.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path("
                              f"{str(ROOT / 'modules/self-hosted/ghostship-notify.py')!r}, run_name='__main__')\n")
            notify.chmod(0o700)
            config = root / "config.json"
            config.write_text(json.dumps({"command": [sys.executable, str(monitor), str(report)],
                                          "notify": str(notify), "state": str(root / "state.json")}))
            env = {**os.environ, "GHOSTSHIP_NOTIFY_STATE": str(root / "notify-state"),
                   "GHOSTSHIP_NOTIFY_SECRETS": str(secrets), "GHOSTSHIP_NOTIFY_INCIDENTS": str(spool),
                   "GHOSTSHIP_NOTIFY_URL": f"http://127.0.0.1:{server.server_port}"}

            def run(healthy):
                now = datetime.now(timezone.utc)
                report.write_text(json.dumps({"checked_at": now.isoformat(),
                    "issue_date": now.astimezone(health.ZoneInfo("Pacific/Honolulu")).date().isoformat(),
                    "healthy": healthy, "unhealthy_reasons": [] if healthy else ["delivery_missing"],
                    "last_due_delivery": {"status": "current" if healthy else "missing"}}))
                subprocess.run([sys.executable, str(SCRIPT), "--config", str(config)],
                               env=env, capture_output=True, text=True, check=True, timeout=10)

            run(True)  # No startup success noise.
            self.assertEqual(messages, [])
            available[0] = False
            run(False)  # Incident still queued while ntfy is down.
            self.assertEqual(len(list(spool.glob("*.json"))), 1)
            available[0] = True
            run(False)
            run(False)  # Persistent failure stays in its existing episode.
            self.assertEqual(len(messages), 1)
            pointers = [json.loads(p.read_text()) for p in spool.glob("*.json")]
            self.assertEqual({p["key"] for p in pointers}, {"newsletter-runtime"})
            self.assertEqual(len(pointers), 2)  # Safe retry of the same coordinator key.
            available[0] = False
            run(True)  # Failed resolution is retried.
            self.assertTrue(json.loads((root / "state.json").read_text())["firing"])
            available[0] = True
            run(True)
            run(True)
            self.assertEqual([m["tags"][1] for m in messages], ["firing", "resolved"])
            self.assertEqual(json.loads((root / "state.json").read_text()), {})
            run(False)  # A later episode can alert again.
            self.assertEqual([m["tags"][1] for m in messages], ["firing", "resolved", "firing"])
            self.assertEqual(len(list(spool.glob("*.json"))), 3)


if __name__ == "__main__":
    unittest.main()
