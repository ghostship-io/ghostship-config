import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class OpenCodeCompatibility(unittest.TestCase):
    def test_actual_exec_preserves_prompt_and_changes_directory(self):
        adapter = (
            Path(__file__).resolve().parents[1] / "packages/t3code/opencode-compat.py"
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capture"
            target.write_text(
                f"#!{sys.executable}\nimport os,sys,json\nprint(json.dumps([os.getcwd(),sys.argv[1:]]))\n"
            )
            target.chmod(0o755)
            prompt = "literal prompt with spaces, $variables and `backticks`"
            result = subprocess.check_output(
                [
                    sys.executable,
                    str(adapter),
                    str(target),
                    "run",
                    "--dir",
                    directory,
                    "--log-level",
                    "ERROR",
                    prompt,
                ],
                text=True,
            )
            cwd, arguments = json.loads(result)
            self.assertEqual(cwd, os.path.realpath(directory))
            self.assertEqual(arguments, ["run", "--log-level", "error", prompt])

    def test_serve_arguments_are_unchanged(self):
        import importlib.util

        path = (
            Path(__file__).resolve().parents[1] / "packages/t3code/opencode-compat.py"
        )
        spec = importlib.util.spec_from_file_location("opencode_compat", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = ["serve", "--port", "12345"]
        self.assertEqual(module.translate(args), (None, args))
