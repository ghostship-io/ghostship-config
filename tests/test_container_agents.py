"""The container bootstrap delegates to the selected Ghostship checkout."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ContainerAgentsTest(unittest.TestCase):
    def test_delegates_arguments_to_source_installer(self):
        wrapper = Path(__file__).resolve().parents[1] / "scripts/setup-container-agents.py"
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            installer = source / "tools/setup-container-agents.py"
            installer.parent.mkdir()
            installer.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
            args = ["--source", str(source), "--skills-only", "--home", str(source / "home")]
            result = subprocess.check_output([sys.executable, str(wrapper), *args], text=True)
            self.assertEqual(json.loads(result), args)


if __name__ == "__main__":
    unittest.main()
