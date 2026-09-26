import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

from test_config import load

updater = load("t3code_antigravity", "packages/t3code/update-antigravity.py")

BINARIES = ("agy_acp_server.par", "localharness_external")


def release(version="1.2.0", legacy=True):
    prefix = "agy-acp-server-agy_acp_server_" if legacy else "agy-acp-server-"
    base = (
        "https://dl.google.com/agy-extensions/releases/linux/"
        f"{prefix}{version}-linux"
    )
    return {
        "version": version,
        "distribution": {
            "binary": {
                "linux-x86_64": {"archive": f"{base}-x86_64.zip"},
                "linux-aarch64": {"archive": f"{base}-arm64.zip"},
            }
        },
    }


def archive(_url, destination):
    with zipfile.ZipFile(destination, "w") as package:
        for name in BINARIES:
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
            for name in BINARIES:
                self.assertEqual((candidate / name).read_text(), f"new {name}")
            self.assertEqual(
                sorted(p.name for p in candidate.iterdir()), sorted(BINARIES)
            )

        self.assertTrue(
            updater.update(
                self.root, "1.1.1", release(), "probe", archive, check, "x86_64"
            )
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
                "x86_64",
            )
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertFalse(list(self.root.glob(".staging-*")))

    def test_incomplete_download_preserves_previous_release(self):
        def incomplete(_url, destination):
            with zipfile.ZipFile(destination, "w") as package:
                package.writestr("agy_acp_server.par", "server without helper")

        check = Mock()
        with self.assertRaises(KeyError):
            updater.update(
                self.root, "1.1.1", release(), "probe", incomplete, check, "x86_64"
            )
        check.assert_not_called()
        self.assertEqual((self.root / "current").resolve(), self.old)

    def test_no_download_for_same_or_older_version(self):
        fetch = Mock()
        for version in ("1.1.1", "1.0.0"):
            self.assertFalse(
                updater.update(
                    self.root, "1.1.1", release(version), "probe", fetch, machine="x86_64"
                )
            )
        fetch.assert_not_called()

    def test_image_fallback_does_not_require_persistent_runtime(self):
        (self.root / "current").unlink()
        fetch = Mock()
        self.assertFalse(
            updater.update(self.root, "1.2.0", release(), "probe", fetch, machine="x86_64")
        )
        fetch.assert_not_called()

    def test_rejects_unexpected_download_source(self):
        data = release()
        data["distribution"]["binary"]["linux-x86_64"]["archive"] = (
            "https://example.com/a.zip"
        )
        with self.assertRaises(ValueError):
            updater.release_info(data, "x86_64")
        with self.assertRaises(ValueError):
            updater.release_info(release("../../bad"), "x86_64")

    def test_arm64_host_stages_native_harness(self):
        _, archives = updater.release_info(release(), "aarch64")
        self.assertTrue(archives["agy_acp_server.par"].endswith("-x86_64.zip"))
        self.assertTrue(archives["localharness_external"].endswith("-arm64.zip"))

    def test_x86_64_host_stages_matching_harness(self):
        _, archives = updater.release_info(release(), "x86_64")
        self.assertTrue(archives["agy_acp_server.par"].endswith("-x86_64.zip"))
        self.assertTrue(archives["localharness_external"].endswith("-x86_64.zip"))

    def test_accepts_modern_archive_naming_scheme(self):
        modern = release(version="1.2.1", legacy=False)
        version, archives = updater.release_info(modern, "aarch64")
        self.assertEqual(version, "1.2.1")
        self.assertEqual(
            archives["agy_acp_server.par"],
            "https://dl.google.com/agy-extensions/releases/linux/agy-acp-server-1.2.1-linux-x86_64.zip",
        )
        self.assertEqual(
            archives["localharness_external"],
            "https://dl.google.com/agy-extensions/releases/linux/agy-acp-server-1.2.1-linux-arm64.zip",
        )


if __name__ == "__main__":
    unittest.main()
