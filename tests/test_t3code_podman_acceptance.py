"""A redirected or production socket must be refused before any mutation."""

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = (
    Path(__file__).resolve().parents[1] / "packages/t3code/dev-engine/acceptance.py"
)
spec = importlib.util.spec_from_file_location("acceptance", SOURCE)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class CandidateAdmission(unittest.TestCase):
    def test_production_rootful_and_missing_identity_never_reach_a_mutation(self):
        for info in (
            {},
            {
                "store": {"graphRoot": "/var/lib/t3code-podman/storage"},
                "host": {"security": {"rootless": True}},
            },
            {
                "store": {"graphRoot": "/var/lib/t3code-podman/candidate"},
                "host": {"security": {"rootless": False}},
            },
        ):
            with self.subTest(info=info), tempfile.TemporaryDirectory() as directory:
                report = Path(directory) / "control.json"
                endpoint = "127.0.0.1:12345"
                report.write_text(
                    json.dumps(
                        {"observed_at": time.time(), "endpoints": {endpoint: True}}
                    )
                )
                args = [
                    "acceptance",
                    "--control-report",
                    str(report),
                    "--denied-endpoint",
                    endpoint,
                ]
                result = subprocess.CompletedProcess([], 0, json.dumps(info), "")
                with (
                    patch.object(sys, "argv", args),
                    patch.object(
                        acceptance.subprocess, "run", return_value=result
                    ) as run,
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as exit_code,
                ):
                    acceptance.main()
                self.assertEqual(exit_code.exception.code, 2)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(
                    run.call_args.args[0][-3:], ["info", "--format", "{{json .}}"]
                )
