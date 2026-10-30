"""Run the real health entrypoint; double only WARP/systemd external transports."""
import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "modules/common/mesh-health.py"
TEAM = {"account": {"type": "team", "organization": "ghostshipio"}}
TRANSPORT = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ["MESH_FIXTURE"])
d = json.loads(p.read_text())
args = sys.argv[1:]
result = {}
code = 0
if d.get("daemonUnavailable") and "restart" not in args:
    code = 1
elif "registration" in args:
    if d.get("unknown"):
        print("opaque-secret-do-not-log", file=sys.stderr)
        code = 1
    else:
        result = d.get("registration", {})
        code = 0 if result else 1
elif "connector" in args:
    d["enrollments"] = d.get("enrollments", 0) + 1
    d["registration"] = {"account": {"type": "team", "organization": "ghostshipio"}, "id": "fixture-identity"}
    code = 1 if d.get("lostAck") else 0
elif "connect" in args:
    d["connects"] = d.get("connects", 0) + 1
    if not d.get("offline"):
        d["status"] = "Connected"
elif "restart" in args:
    d["restarts"] = d.get("restarts", 0) + 1
elif "status" in args:
    result = {"status": d.get("status", "Disconnected")}
p.write_text(json.dumps(d))
print(json.dumps(result))
sys.exit(code)
'''


class MeshLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "health"
        self.state.mkdir()
        self.native = self.root / "warp-state"
        self.native.mkdir()
        self.fixture = self.root / "transport.json"
        self.fixture.write_text("{}")
        self.token = self.root / "token"
        self.token.write_text("opaque-secret-do-not-log")
        self.token.chmod(0o600)
        self.transport = self.root / "external-transport"
        self.transport.write_text(TRANSPORT)
        self.transport.chmod(0o700)

    def data(self):
        return json.loads(self.fixture.read_text())

    def update(self, **data):
        self.fixture.write_text(json.dumps(self.data() | data))

    def run_health(self):
        env = os.environ | {"MESH_FIXTURE": str(self.fixture)}
        start = time.monotonic()
        r = subprocess.run(
            [sys.executable, str(SOURCE), "--warp-cli", str(self.transport),
             "--systemctl", str(self.transport), "--state-dir", str(self.state),
             "--warp-state-dir", str(self.native), "--token-file", str(self.token)],
            env=env, capture_output=True, text=True, timeout=10,
        )
        self.assertNotIn("opaque-secret-do-not-log", r.stdout + r.stderr)
        self.assertLess(time.monotonic() - start, 10)
        return r

    def test_unknown_enrollment_is_reconciled_without_duplicate(self):
        self.update(lostAck=True)
        self.assertNotEqual(self.run_health().returncode, 0)
        self.assertIn("attemptedAt", json.loads((self.state / "enrollment-attempted").read_text()))
        self.assertEqual(self.run_health().returncode, 0)
        self.assertEqual(self.data()["enrollments"], 1)

    def test_concurrent_boot_and_timer_share_one_enrollment(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.run_health(), range(2)))
        self.assertEqual([r.returncode for r in results], [0, 0])
        self.assertEqual(self.data()["enrollments"], 1)
        self.assertEqual(self.data()["registration"]["id"], "fixture-identity")
        state = json.loads((self.state / "health.json").read_text())
        self.assertEqual((state["transport"], state["peers"]), ("connected", "unverified"))
        self.assertEqual((self.state / "health.json").stat().st_mode & 0o777, 0o600)

    def test_slow_daemon_start_defers_enrollment_without_fencing_it(self):
        self.update(daemonUnavailable=True)
        self.assertNotEqual(self.run_health().returncode, 0)
        self.assertFalse((self.state / "enrollment-attempted").exists())
        self.update(daemonUnavailable=False)
        self.assertEqual(self.run_health().returncode, 0)
        self.assertEqual(self.data()["enrollments"], 1)

    def test_unknown_existing_identity_is_never_reenrolled(self):
        self.update(unknown=True, daemonUnavailable=True)
        (self.native / "reg.json").write_text("existing-identity")
        for _ in range(3):
            self.assertNotEqual(self.run_health().returncode, 0)
        self.assertNotIn("enrollments", self.data())
        self.assertEqual((self.native / "reg.json").read_text(), "existing-identity")
        self.assertEqual(self.data()["restarts"], 1)

    def test_outage_recovery_is_bounded_and_resume_reconnects(self):
        self.update(registration=TEAM | {"id": "keep"}, offline=True)
        for _ in range(4):
            self.assertNotEqual(self.run_health().returncode, 0)
        self.assertEqual(self.data()["restarts"], 1)
        self.update(offline=False)
        self.assertEqual(self.run_health().returncode, 0)
        self.assertNotIn("enrollments", self.data())
        self.assertEqual(json.loads((self.state / "health.json").read_text())["failures"], 0)

    def test_consumer_registration_and_insecure_token_are_refused(self):
        for account in ({"type": "free"}, {"type": "team", "organization": "other-team"}):
            self.update(registration={"account": account})
            self.assertNotEqual(self.run_health().returncode, 0)
            self.assertNotIn("connects", self.data())
            self.assertNotIn("enrollments", self.data())
        self.assertEqual(json.loads((self.state / "health.json").read_text())["transport"], "unknown")
        self.fixture.write_text("{}")
        self.token.chmod(0o644)
        self.assertNotEqual(self.run_health().returncode, 0)
        self.assertFalse((self.state / "enrollment-attempted").exists())

    def test_bad_peer_configuration_does_not_restart_healthy_daemon(self):
        self.update(registration=TEAM, status="Connected")
        (self.state / "peers.json").write_text('[{"host":"192.0.2.1"}]')
        self.assertNotEqual(self.run_health().returncode, 0)
        self.assertNotIn("restarts", self.data())
        self.assertEqual(json.loads((self.state / "health.json").read_text())["peers"],
                         "unreachable-or-invalid")


if __name__ == "__main__":
    unittest.main()
