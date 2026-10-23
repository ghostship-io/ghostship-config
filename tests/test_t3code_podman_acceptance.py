"""A redirected or production socket must be refused before any mutation."""

import contextlib
import importlib.util
import io
import json
import re
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


class NativeNetworkInspection(unittest.TestCase):
    def test_project_networks_read_native_subnets(self):
        # Docker-shaped inspection silently discarded Podman's subnet evidence.
        def command(*args, **kwargs):
            output = (
                "project_default\n"
                if args[1] == "ls"
                else json.dumps(
                    [{"driver": "bridge", "subnets": [{"subnet": "192.0.2.0/24"}]}]
                )
            )
            return subprocess.CompletedProcess(args, 0, output, "")

        self.assertEqual(
            acceptance.project_networks(command, "project"),
            {"project_default": {"driver": "bridge", "subnets": ["192.0.2.0/24"]}},
        )


class ImageStartup(unittest.TestCase):
    def test_readiness_unit_executes_the_packaged_command(self):
        # A stale executable name prevents the bootstrap and server from starting.
        source = (SOURCE.parents[3] / "packages/t3code/image.nix").read_text()
        # This is the stable executable contract exported by ghostship-agent;
        # the image must resolve it through the persistent home payload.
        self.assertIn("ExecStart=${managedBin}/t3code-engine-ready\n", source)



class PublishedPort(unittest.TestCase):
    def test_absent_or_bare_provider_ports_do_not_abort_the_report(self):
        # podman-compose can print None after a failed project start.
        for output in ("", "None\n", "0.0.0.0:22", "70000"):
            self.assertIsNone(acceptance.published_tcp_port(output))
        self.assertEqual(acceptance.published_tcp_port("127.0.0.1:32123\n"), 32123)
        self.assertEqual(acceptance.published_tcp_port("32123\n"), 32123)
