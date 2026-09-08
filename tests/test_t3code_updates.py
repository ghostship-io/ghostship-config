import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

from test_config import load

updater = load("t3code_antigravity", "packages/t3code/update-antigravity.py")


def release(version="1.2.0"):
    return {
        "version": version,
        "distribution": {
            "binary": {
                "linux-x86_64": {
                    "archive": (
                        "https://dl.google.com/agy-extensions/releases/linux/"
                        f"agy-acp-server-agy_acp_server_{version}-linux-x86_64.zip"
                    )
                }
            }
        },
    }


def archive(_url, destination):
    with zipfile.ZipFile(destination, "w") as package:
        for name in updater.BINARIES:
            package.writestr(name, f"new {name}")
        package.writestr("../../outside", "must not be extracted")


class AntigravityUpdates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "old"
        self.old.mkdir()
        (self.old / "release.json").write_text(json.dumps({"version": "1.1.1"}))
        (self.root / "current").symlink_to(self.old)

    def test_switches_server_and_helper_only_after_probe(self):
        def check(candidate, _probe):
            self.assertEqual((self.root / "current").resolve(), self.old)
            for name in updater.BINARIES:
                self.assertEqual((candidate / name).read_text(), f"new {name}")
            self.assertEqual(
                sorted(p.name for p in candidate.iterdir()), sorted(updater.BINARIES)
            )

        self.assertTrue(
            updater.update(self.root, "1.1.1", release(), "probe", archive, check)
        )
        active = (self.root / "current").resolve()
        self.assertNotEqual(active, self.old)
        self.assertEqual(
            json.loads((active / "release.json").read_text())["version"], "1.2.0"
        )
        self.assertTrue(self.old.exists())

    def test_failed_probe_preserves_previous_release(self):
        with self.assertRaisesRegex(RuntimeError, "bad protocol"):
            updater.update(
                self.root,
                "1.1.1",
                release(),
                "probe",
                archive,
                Mock(side_effect=RuntimeError("bad protocol")),
            )
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertFalse(list(self.root.glob(".staging-*")))

    def test_incomplete_download_preserves_previous_release(self):
        def incomplete(_url, destination):
            with zipfile.ZipFile(destination, "w") as package:
                package.writestr("agy_acp_server.par", "server without helper")

        check = Mock()
        with self.assertRaises(KeyError):
            updater.update(self.root, "1.1.1", release(), "probe", incomplete, check)
        check.assert_not_called()
        self.assertEqual((self.root / "current").resolve(), self.old)

    def test_no_download_for_same_or_older_version(self):
        fetch = Mock()
        for version in ("1.1.1", "1.0.0"):
            self.assertFalse(
                updater.update(self.root, "1.1.1", release(version), "probe", fetch)
            )
        fetch.assert_not_called()

    def test_image_fallback_does_not_require_persistent_runtime(self):
        (self.root / "current").unlink()
        fetch = Mock()
        self.assertFalse(updater.update(self.root, "1.2.0", release(), "probe", fetch))
        fetch.assert_not_called()

    def test_rejects_unexpected_download_source(self):
        data = release()
        data["distribution"]["binary"]["linux-x86_64"]["archive"] = (
            "https://example.com/a.zip"
        )
        with self.assertRaises(ValueError):
            updater.release_info(data)
        with self.assertRaises(ValueError):
            updater.release_info(release("../../bad"))
