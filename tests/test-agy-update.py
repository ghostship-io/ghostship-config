"""Check CLI update validation preserves the installed binary on failure."""

import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "update_agy", Path(__file__).parents[1] / "packages/t3code/update-agy.py"
)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class UpdateTests(unittest.TestCase):
    def run_update(self, *, bad_hash=False, bad_version=False):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = home / ".local/bin/agy"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"previous")
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w:gz") as archive:
                binary = b"new binary"
                member = tarfile.TarInfo("antigravity")
                member.size = len(binary)
                archive.addfile(member, io.BytesIO(binary))
            data = payload.getvalue()
            release = {
                "version": "1.2.3",
                "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/test.tar.gz",
                "sha512": "bad" if bad_hash else hashlib.sha512(data).hexdigest(),
            }
            with (
                patch.object(updater.Path, "home", return_value=home),
                patch.object(
                    updater.urllib.request,
                    "urlopen",
                    side_effect=[
                        io.BytesIO(json.dumps(release).encode()),
                        io.BytesIO(data),
                    ],
                ),
                patch.object(
                    updater.subprocess,
                    "check_output",
                    side_effect=["1.2.2", "invalid" if bad_version else "1.2.3"],
                ),
            ):
                if bad_hash or bad_version:
                    with self.assertRaises(ValueError):
                        updater.main()
                    self.assertEqual(target.read_bytes(), b"previous")
                else:
                    updater.main()
                    self.assertEqual(target.read_bytes(), binary)
                    self.assertEqual(target.stat().st_mode & 0o777, 0o755)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_valid_update(self):
        self.run_update()

    def test_checksum_failure_preserves_install(self):
        self.run_update(bad_hash=True)

    def test_probe_failure_preserves_install(self):
        self.run_update(bad_version=True)


if __name__ == "__main__":
    unittest.main()
