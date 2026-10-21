"""Container metadata snapshot (siem/podman-snapshot.py) and its reader in the alert bridge."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/siem"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snap = load("siem_snapshot", "podman-snapshot.py")
alerts = load("siem_alerts_snapshot", "alerts.py")

INSPECT = [
    {"Id": "g1", "Name": "gluetun", "State": {"Pid": 10, "Status": "running"},
     "HostConfig": {"NetworkMode": "bridge"},
     "NetworkSettings": {"Networks": {"ghostship_net": {"IPAddress": "10.89.0.5"}}},
     "Config": {"Env": ["SECRET=x"]}},
    {"Id": "q1", "Name": "qbittorrent", "State": {"Pid": 11, "Status": "running"},
     "HostConfig": {"NetworkMode": "container:g1"},
     "NetworkSettings": {"Networks": {"ghostship_net": {"IPAddress": "10.89.0.5"}}}},
]


class SnapshotTests(unittest.TestCase):
    def test_metadata_only_and_netns_owner(self):
        meta = snap.snapshot(INSPECT)
        self.assertEqual(meta["qbittorrent"]["netns_owner"], "gluetun")
        self.assertIsNone(meta["gluetun"]["netns_owner"])
        self.assertNotIn("SECRET", json.dumps(meta))

    def test_shared_namespace_traffic_counted_once(self):
        files = {"/proc/10/cgroup": "0::/a\n", "/proc/11/cgroup": "0::/b\n",
                 "/proc/10/net/dev": "h\nh\n  lo: 5 0 0 0 0 0 0 0 5\n eth0: 100 0 0 0 0 0 0 0 40\n tun0: 70 0 0 0 0 0 0 0 30\n"}
        with mock.patch.object(snap, "read", lambda p: files.get(p)):
            rows, shared = snap.counters(snap.snapshot(INSPECT))
        text = snap.render(rows, shared)
        self.assertIn('ghostship_container_network_transmit_bytes_total{container="gluetun"} 40', text)
        self.assertNotIn('network_transmit_bytes_total{container="qbittorrent"}', text)
        self.assertIn('ghostship_container_netns_shared{container="qbittorrent",netns_owner="gluetun"} 1', text)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "containers.json"
        self.path.write_text(json.dumps(snap.snapshot(INSPECT)))

    def tearDown(self):
        self.dir.cleanup()

    def test_resolves_address(self):
        self.assertEqual(alerts.container_address("gluetun", "ghostship_net", self.path), "10.89.0.5")

    def test_stale_or_missing_snapshot_fails_closed(self):
        os.utime(self.path, (1, 1))
        with self.assertRaises(OSError):
            alerts.container_address("gluetun", "ghostship_net", self.path)
        with self.assertRaises(OSError):
            alerts.container_address("nope", "ghostship_net", self.path, now=self.path.stat().st_mtime)

    def test_bridge_has_no_podman_socket_code(self):
        source = (ROOT / "alerts.py").read_text()
        self.assertNotIn("podman.sock", source)


if __name__ == "__main__":
    unittest.main()
