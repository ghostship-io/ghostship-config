"""Lease-range migration preserves network identity, endpoints and rollback data."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "packages/podman-network/range.py"
spec = importlib.util.spec_from_file_location("network_range", SOURCE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

SPEC = {"name": "ghostship_net", "subnet": "192.0.2.0/24", "gateway": "192.0.2.1", "start": "192.0.2.32", "end": "192.0.2.254"}
NETWORK = {"name": "ghostship_net", "id": "synthetic", "driver": "bridge", "network_interface": "fixture0", "ipv6_enabled": False, "dns_enabled": True, "ipam_options": {"driver": "host-local"}, "subnets": [{"subnet": "192.0.2.0/24", "gateway": "192.0.2.1"}], "labels": {"fixture": "preserve"}}


class LeaseRange(unittest.TestCase):
    def test_only_lease_range_changes_and_reapplication_converges(self):
        before = json.loads(json.dumps(NETWORK))
        updated = policy.changed_network(before, SPEC)
        self.assertEqual(before, NETWORK)
        self.assertEqual(policy.changed_network(updated, SPEC), updated)
        lease = updated["subnets"][0].pop("lease_range")
        self.assertEqual(lease, {"start_ip": SPEC["start"], "end_ip": SPEC["end"]})
        self.assertEqual(updated, NETWORK)

    def test_other_backend_or_network_identity_is_refused(self):
        for key, value in (("name", "other"), ("driver", "macvlan"), ("ipv6_enabled", True), ("ipam_options", {"driver": "none"}), ("subnets", [])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                policy.changed_network(NETWORK | {key: value}, SPEC)

    def test_invalid_or_gateway_overlapping_ranges_are_refused(self):
        for start, end in (("192.0.2.0", "192.0.2.254"), ("192.0.2.1", "192.0.2.31"), ("192.0.2.32", "192.0.2.255"), ("192.0.2.99", "192.0.2.32"), ("192.0.3.32", "192.0.3.254")):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                policy.changed_network(NETWORK, SPEC | {"start": start, "end": end})

    def test_atomic_replace_preserves_mode_and_original_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network.json"
            path.write_bytes(b"original")
            descriptor = os.open(path, os.O_RDONLY)
            try:
                policy.atomic_write(path, b"updated", 0o600)
                self.assertEqual(path.read_bytes(), b"updated")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(os.read(descriptor, 20), b"original")
                self.assertEqual(list(Path(directory).iterdir()), [path])
            finally:
                os.close(descriptor)

    def test_symlink_cannot_redirect_protected_file_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target").touch()
            (root / "link").symlink_to(root / "target")
            with self.assertRaises(OSError):
                policy.trusted_open(root / "link", os.O_RDONLY)
