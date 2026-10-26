"""A unit start must wait for its executable in the worker container's store.

Issue #639: a switch restart raced the runtime publisher, the exec reached the
container before the new closure was published, `podman exec` exited 127 and
the switch failed. The gate must keep waiting while the path is absent, stop as
soon as it appears, and fail closed on timeout instead of execing a missing
path. A container that cannot accept an exec yet is not a reason to stop early.
"""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


source = Path(__file__).resolve().parents[1] / "modules/self-hosted/inference-container-wait.py"
spec = importlib.util.spec_from_file_location("container_wait", source)
container_wait = importlib.util.module_from_spec(spec)
spec.loader.exec_module(container_wait)

PATH = "/nix/store/new-closure/bin/ghostship-free-inference-bridge"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def completed(command, returncode):
    return subprocess.CompletedProcess(command, returncode)


class ContainerWaitTest(unittest.TestCase):
    def test_gate_checks_the_exact_path_in_the_worker_container(self):
        calls = []
        container_wait.wait(
            "/podman", "ghostship-worker", PATH, 5,
            run=lambda command, **options: calls.append(command) or completed(command, 0),
            sleep=lambda _: self.fail("a ready path must not sleep"),
            clock=lambda: 0.0,
        )
        self.assertEqual(
            calls,
            [["/podman", "exec", "--user", "0:0", "ghostship-worker",
              "/bin/test", "-x", PATH]],
        )

    def test_gate_keeps_waiting_until_the_closure_lands(self):
        clock = Clock()
        statuses = iter([127, 127, 0])
        container_wait.wait(
            "/podman", "ghostship-worker", PATH, 10,
            run=lambda command, **options: completed(command, next(statuses)),
            sleep=clock.sleep, clock=clock,
        )
        self.assertEqual(clock.now, 4)

    def test_gate_fails_closed_when_the_path_never_appears(self):
        clock = Clock()
        with self.assertRaisesRegex(
            TimeoutError, f"{PATH} is not executable in ghostship-worker after 3s"
        ):
            container_wait.wait(
                "/podman", "ghostship-worker", PATH, 3,
                run=lambda command, **options: completed(command, 127),
                sleep=clock.sleep, clock=clock,
            )

    def test_gate_retries_a_container_that_cannot_exec_yet(self):
        clock = Clock()
        attempts = []

        def run(command, **options):
            attempts.append(command)
            if len(attempts) == 1:
                raise subprocess.TimeoutExpired(command, 30)
            return completed(command, 0)

        container_wait.wait(
            "/podman", "ghostship-worker", PATH, 10,
            run=run, sleep=clock.sleep, clock=clock,
        )
        self.assertEqual(len(attempts), 2)

    def test_command_line_reports_a_missing_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            podman = Path(directory) / "podman"
            podman.write_text("#!/bin/sh\nexit 127\n")
            podman.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(source), str(podman), "ghostship-worker",
                 PATH, "--timeout", "0"],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{PATH} is not executable in ghostship-worker", result.stderr)

    def test_command_line_passes_once_the_executable_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            podman = Path(directory) / "podman"
            podman.write_text("#!/bin/sh\nexit 0\n")
            podman.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(source), str(podman), "ghostship-worker",
                 PATH, "--timeout", "0"],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
