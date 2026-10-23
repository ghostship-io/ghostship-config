"""Newsletter monitor -> real notifier -> isolated incident spool and fake ntfy."""
import importlib.util
import contextlib
import hashlib
import io
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

class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exercise the deployed consumer contract from this repository's pinned
        # dependency, not a second implementation of incident deduplication.
        source = os.environ.get("GHOSTSHIP_TEST_AGENT_SOURCE")
        if not source:
            source = subprocess.check_output([
                "nix", "eval", "--impure", "--raw", "--expr",
                "(builtins.getFlake (toString ./.)).inputs.ghostship-private-agent.outPath",
            ], cwd=ROOT, text=True, timeout=60).strip()
        sys.path.insert(0, str(Path(source) / "tools/python"))
        spec = importlib.util.spec_from_file_location(
            "pinned_coordinator", Path(source) / "tools/python/ghostship_github/coordinator.py")
        cls.coordinator_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.coordinator_module)

    def setUp(self):
        self.messages = []
        self.available = True
        owner = self

        class Ntfy(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if owner.available:
                    owner.messages.append(payload)
                self.send_response(200 if owner.available else 503)
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Ntfy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.spool = self.root / "incidents"
        self.spool.mkdir()
        secrets = self.root / "monitoring.env"
        secrets.write_text("NTFY_PUBLISH_PASSWORD=fake-test-password\n")
        self.report = self.root / "report.json"
        monitor = self.root / "monitor.py"
        monitor.write_text("import json,sys\np=json.load(open(sys.argv[1]))\n"
                           "print(json.dumps(p))\nsys.exit(0 if p['healthy'] else 4)\n")
        notify = self.root / "notify"
        notify.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path("
                          f"{str(ROOT / 'modules/self-hosted/ghostship-notify.py')!r}, run_name='__main__')\n")
        notify.chmod(0o700)
        self.config = self.root / "config.json"
        self.state = self.root / "state.json"
        self.config.write_text(json.dumps({"command": [sys.executable, str(monitor), str(self.report)],
                                          "notify": str(notify), "state": str(self.state)}))
        self.env = {**os.environ, "GHOSTSHIP_NOTIFY_STATE": str(self.root / "notify-state"),
                    "GHOSTSHIP_NOTIFY_SECRETS": str(secrets), "GHOSTSHIP_NOTIFY_INCIDENTS": str(self.spool),
                    "GHOSTSHIP_NOTIFY_URL": f"http://127.0.0.1:{server.server_port}"}
        self.bridge = mock.Mock()
        # The broker reconciles native ownership/capacity before a launch.
        self.bridge.shell.return_value = {"threads": [], "archivedThreads": []}
        # Native launch receipts return the reserved caller-provided identity.
        def accepted_launch(*_args, **kwargs):
            thread_id = kwargs["thread_id"]
            self.bridge.shell.return_value["threads"].append({
                "id": thread_id, "title": "Worker: incident recovery", "projectId": "test-project"})
            return {"thread_id": thread_id}
        self.bridge.launch.side_effect = accepted_launch
        store = self.coordinator_module.Store(self.root / "coordinator.sqlite")
        self.addCleanup(store.db.close)
        self.coordinator = self.coordinator_module.Coordinator({
            "orchestrator_thread_id": "test-orchestrator",
            "allowed_user_ids": [], "repositories": {"ghostship-io/ghostship-config": {"project_id": "test-project"}},
            "model_selection": {"instanceId": "codex", "model": "gpt-6.1-sol"},
            "incidents": {"repository": "ghostship-io/ghostship-config", "daily_limit": 3,
                          "recurrence_cooldown": 0},
        }, store, mock.Mock(), bridge=lambda: self.bridge)

    def consume(self):
        count = self.coordinator.ingest(self.spool, incidents=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.coordinator.process()
        return count

    def run_monitor(self, healthy):
        now = datetime.now(timezone.utc)
        self.report.write_text(json.dumps({"checked_at": now.isoformat(),
            "issue_date": now.astimezone(health.ZoneInfo("Pacific/Honolulu")).date().isoformat(),
            "healthy": healthy, "unhealthy_reasons": [] if healthy else ["delivery_missing"],
            "last_due_delivery": {"status": "current" if healthy else "missing"}}))
        subprocess.run([sys.executable, str(SCRIPT), "--config", str(self.config)],
                       env=self.env, capture_output=True, text=True, check=True, timeout=10)

    def test_ntfy_outage_retries_notification_without_requeuing_incident(self):
        self.run_monitor(True)
        self.assertEqual(self.messages, [])
        self.available = False
        for expected in (1, 0, 0):
            self.run_monitor(False)
            self.assertEqual(self.consume(), expected)
        self.assertEqual(self.bridge.launch.call_count, 1)
        self.bridge.send.assert_not_called()
        self.available = True
        self.run_monitor(False)
        self.run_monitor(False)
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.consume(), 0)
        self.available = False
        self.run_monitor(True)
        recovered = json.loads(self.state.read_text())
        self.assertFalse(recovered["firing"])
        self.assertTrue(recovered["pending_resolution"])
        self.available = True
        self.run_monitor(True)
        self.run_monitor(True)
        self.assertEqual([m["tags"][1] for m in self.messages], ["firing", "resolved"])
        self.assertEqual(json.loads(self.state.read_text()), {})
        self.run_monitor(False)
        self.assertEqual(self.consume(), 1)
        self.assertEqual(self.bridge.launch.call_count, 1)
        self.assertEqual(self.bridge.send.call_count, 1)  # A new episode, not an ntfy retry.

    def test_spool_failure_retries_handoff_even_after_ntfy_success(self):
        self.spool.rmdir()
        self.spool.write_text("blocked spool")
        self.run_monitor(False)
        self.run_monitor(False)
        self.assertEqual(len(self.messages), 1)
        self.spool.unlink()
        self.spool.mkdir()
        self.run_monitor(False)
        self.run_monitor(False)
        self.assertEqual(len(list(self.spool.glob("*.json"))), 1)
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.consume(), 1)
        self.assertEqual(self.bridge.launch.call_count, 1)
        self.bridge.send.assert_not_called()

    def test_relapse_during_resolution_outage_gets_a_new_incident_and_firing(self):
        self.run_monitor(False)
        (first,) = self.spool.glob("*.json")
        first_id = json.loads(self.state.read_text())["incident_id"]
        self.assertEqual(self.consume(), 1)
        # An existing on-disk episode must keep its ID across the upgrade.
        self.state.write_text(json.dumps({"firing": True, "incident_id": first_id,
                                          "incident_queued": True, "notified": True}))
        self.available = False
        self.run_monitor(False)
        self.assertEqual(json.loads(self.state.read_text())["incident_id"], first_id)
        self.run_monitor(True)
        self.run_monitor(False)
        (second,) = self.spool.glob("*.json")
        second_id = json.loads(self.state.read_text())["incident_id"]
        self.assertNotEqual(second_id, first_id)
        self.assertNotEqual(second.name, first.name)
        self.assertEqual(self.consume(), 1)
        self.assertEqual(self.bridge.send.call_count, 1)
        self.run_monitor(False)
        self.assertEqual(json.loads(self.state.read_text())["incident_id"], second_id)
        self.assertEqual(self.consume(), 0)
        self.available = True
        self.run_monitor(False)
        self.run_monitor(False)
        self.assertEqual([m["tags"][1] for m in self.messages],
                         ["firing", "resolved", "firing"])
        self.assertEqual(self.bridge.launch.call_count, 1)
        self.assertEqual(self.bridge.send.call_count, 1)
        self.run_monitor(True)
        self.assertEqual([m["tags"][1] for m in self.messages],
                         ["firing", "resolved", "firing", "resolved"])
        self.assertEqual(json.loads(self.state.read_text()), {})

    def test_flapping_with_spool_outage_retains_bounded_durable_handoffs(self):
        self.spool.rmdir()
        self.available = False
        identities = []
        sizes = []
        for _ in range(8):
            self.run_monitor(False)
            identities.append(json.loads(self.state.read_text())["incident_id"])
            self.run_monitor(True)
            sizes.append(self.state.stat().st_size)
        self.assertEqual(len(set(identities)), len(identities))
        # Pending episodes must not grow an unbounded list during an outage.
        self.assertLess(max(sizes) - min(sizes), 64)
        self.spool.mkdir()
        queued = []
        for _ in identities:
            self.run_monitor(True)
            (event,) = self.spool.glob("*.json")
            queued.append(event.name)
            self.assertEqual(self.consume(), 1)
        self.assertEqual(queued, [f"incident-{hashlib.sha256(event_id.encode()).hexdigest()}.json"
                                  for event_id in identities])
        self.assertEqual(self.bridge.launch.call_count, 1)
        self.assertEqual(self.bridge.send.call_count, self.coordinator_module.WAKE_LIMIT)
        thread_id = self.bridge.launch.call_args.kwargs["thread_id"]
        digest = json.loads(self.coordinator.store.meta("digest:" + thread_id))
        self.assertEqual(len(digest["pending"]), len(identities) - 1 - self.coordinator_module.WAKE_LIMIT)
        self.available = True
        self.run_monitor(True)
        self.run_monitor(True)
        self.assertEqual([m["tags"][1] for m in self.messages], ["resolved"])
        self.assertEqual(list(self.spool.iterdir()), [])
        self.assertEqual(json.loads(self.state.read_text()), {})

    def test_lost_handoff_acknowledgement_replays_the_same_coordinator_event(self):
        replace = os.replace
        queued = []

        def lose_acknowledgement(source, destination):
            events = list(self.spool.glob("*.json"))
            if events:
                queued.extend(events)
                self.assertEqual(self.consume(), 1)
                raise OSError("injected failure persisting handoff acknowledgement")
            return replace(source, destination)

        with mock.patch.dict(os.environ, self.env), \
             mock.patch.object(health, "observe", return_value="delivery_missing"), \
             mock.patch.object(health.os, "replace", side_effect=lose_acknowledgement):
            with self.assertRaisesRegex(OSError, "persisting handoff acknowledgement"):
                health.main(["--config", str(self.config)])
        self.run_monitor(False)
        (retried,) = self.spool.glob("*.json")
        self.assertEqual(retried.name, queued[0].name)
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.consume(), 0)  # Stable filename is the coordinator's deduplication key.
        self.assertEqual(self.bridge.launch.call_count, 1)
        self.bridge.send.assert_not_called()
        self.run_monitor(False)
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_recovery_does_not_drop_unacknowledged_handoff(self):
        self.spool.rmdir()
        self.run_monitor(False)
        self.run_monitor(True)
        recovered = json.loads(self.state.read_text())
        self.assertFalse(recovered["firing"])
        self.assertFalse(recovered.get("pending_resolution"))
        # Adopt a pre-upgrade recovery whose resolution succeeded before its
        # incident could be queued; that pending event must keep its original ID.
        self.state.write_text(json.dumps({"firing": True, "incident_id": recovered["incident_id"],
            "incident_queued": False, "notified": True, "resolved": True}))
        self.spool.mkdir()
        self.run_monitor(True)
        (event,) = self.spool.glob("*.json")
        self.assertEqual(event.name,
                         f'incident-{hashlib.sha256(recovered["incident_id"].encode()).hexdigest()}.json')
        self.assertEqual(self.consume(), 1)
        self.assertEqual(json.loads(self.state.read_text()), {})
        self.assertEqual([m["tags"][1] for m in self.messages], ["firing", "resolved"])

    def test_identity_must_be_persisted_before_handoff(self):
        for previous in (None, {"firing": True, "incident_id": "existing-episode",
                               "incident_queued": True, "notified": True, "resolved": True}):
            with self.subTest(previous=previous):
                if previous is not None:
                    self.state.write_text(json.dumps(previous))
                with mock.patch.object(health, "observe", return_value="delivery_missing"), \
                     mock.patch.object(health.os, "fsync", side_effect=OSError("injected persistence failure")):
                    with self.assertRaises(OSError):
                        health.main(["--config", str(self.config)])
                self.assertEqual(list(self.spool.iterdir()), [])
                self.assertEqual(self.messages, [])
                if previous is None:
                    self.assertFalse(self.state.exists())
                else:
                    self.assertEqual(json.loads(self.state.read_text()), previous)


if __name__ == "__main__":
    unittest.main()
