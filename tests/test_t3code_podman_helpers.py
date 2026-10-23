"""A custom helper path must retain published ports and container init support."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = (
    Path(__file__).resolve().parents[1] / "packages/t3code/dev-engine/check-helpers.py"
)
spec = importlib.util.spec_from_file_location("helpers", SOURCE)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


class ScopedHelpers(unittest.TestCase):
    def test_network_helpers_alone_cannot_admit_the_engine(self):
        # The deployed custom list omitted Podman's own libexec directory.
        with tempfile.TemporaryDirectory() as directory:
            for name in ("netavark", "aardvark-dns"):
                path = Path(directory) / name
                path.touch()
                path.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "rootlessport"):
                helpers.check_helpers({"engine": {"helper_binaries_dir": [directory]}})

    def test_only_executable_helpers_in_the_configured_paths_count(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in helpers.REQUIRED:
                path = Path(directory) / name
                path.touch()
                path.chmod(0o755)
            config = {"engine": {"helper_binaries_dir": [directory]}}
            helpers.check_helpers(config)
            (Path(directory) / "rootlessport").chmod(0o644)
            with self.assertRaisesRegex(ValueError, "rootlessport"):
                helpers.check_helpers(config)
            with self.assertRaises(ValueError):
                helpers.check_helpers({"engine": {"helper_binaries_dir": []}})
