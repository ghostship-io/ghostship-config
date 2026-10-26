"""Exercise container stop with real process identities, signals and exit statuses.

Both `podman exec` units are stopped through the same helper. A clean SIGTERM
inside the container must leave the attachment exiting 0, while a genuine
crash exit 1 must survive to the unit result.
"""

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


source = Path(__file__).resolve().parents[1] / "modules/self-hosted/inference-container-stop.py"
spec = importlib.util.spec_from_file_location("container_stop", source)
container_stop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(container_stop)

# The exact entrypoints systemd matches: the broker, then the scheduler.
ROLES = {
    "broker": ("ghostship_inference.server", ()),
    "scheduler": ("ghostship_inference.cli", ("serve",)),
}


class ContainerStopTest(unittest.TestCase):
    def test_stop_inventories_the_selected_worker_container(self):
        with patch.object(container_stop.os, 'pidfd_open', return_value=91), \
             patch.object(container_stop.os, 'close'), \
             patch.object(container_stop.subprocess, 'check_output', return_value='HPID\n') as inventory:
            with self.assertRaisesRegex(RuntimeError, 'found 0'):
                container_stop.stop(
                    '/podman', 123, 5, container='ghostship-worker',
                    module='ghostship_inference.server')
        inventory.assert_called_once_with(
            ['/podman', 'top', 'ghostship-worker', 'hpid'], text=True, timeout=10)

    def test_already_exited_attachment_with_unset_mainpid_is_a_noop(self):
        result = subprocess.run(
            [sys.executable, str(source), "/unused/podman", "", "ghostship-worker",
             "80", "ghostship_inference.server"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_shutdown(self, role, exit_status=0, *, ignore=False, process=None):
        expected_module, expected_arguments = ROLES[role]
        process_module, process_arguments = process or ROLES[role]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "ghostship_inference"
            package.mkdir()
            (package / "__init__.py").touch()
            (package / f"{process_module.split('.', 1)[1]}.py").write_text(
                "import signal,time\nfrom pathlib import Path\n"
                + ("signal.signal(signal.SIGTERM,signal.SIG_IGN)\n" if ignore else
                   f"signal.signal(signal.SIGTERM,lambda *_:exit({exit_status}))\n")
                + "Path('ready').touch()\nwhile True: time.sleep(1)\n"
            )
            attachment = subprocess.Popen(
                [sys.executable, "-c",
                 "import subprocess,sys; "
                 "p=subprocess.Popen([sys.executable,'-m',sys.argv[1],*sys.argv[2:]]); "
                 "print(p.pid,flush=True); sys.exit(p.wait())",
                 process_module, *process_arguments],
                cwd=root, stdout=subprocess.PIPE, text=True,
            )
            worker = int(attachment.stdout.readline())
            try:
                deadline = time.monotonic() + 5
                while not (root / "ready").exists():
                    if time.monotonic() >= deadline:
                        self.fail("worker did not start")
                    time.sleep(0.01)
                # Only replace the container inventory; process handling is real.
                podman = root / "podman"
                podman.write_text(f"#!{sys.executable}\nprint('HPID\\n{worker}')\n")
                podman.chmod(0o700)
                if process is not None:
                    with self.assertRaisesRegex(RuntimeError, "found 0"):
                        container_stop.stop(
                            str(podman), attachment.pid, 1,
                            container="ghostship-worker",
                            module=expected_module, arguments=expected_arguments)
                    self.assertIsNone(attachment.poll())
                    os.kill(worker, 0)
                elif ignore:
                    with self.assertRaises(TimeoutError):
                        container_stop.stop(
                            str(podman), attachment.pid, 0.1,
                            container="ghostship-worker",
                            module=expected_module, arguments=expected_arguments)
                    self.assertIsNone(attachment.poll())
                else:
                    container_stop.stop(
                        str(podman), attachment.pid, 5,
                        container="ghostship-worker",
                        module=expected_module, arguments=expected_arguments)
                    self.assertEqual(attachment.wait(timeout=1), exit_status)
            finally:
                if attachment.poll() is None:
                    os.kill(worker, signal.SIGKILL)
                    attachment.wait(timeout=5)
                attachment.stdout.close()

    def test_orderly_stop_waits_for_each_role_and_keeps_exit_zero(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.run_shutdown(role)

    def test_real_crash_exit_one_is_preserved_for_each_role(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.run_shutdown(role, exit_status=1)

    def test_the_other_role_is_not_signalled(self):
        for role in ROLES:
            other = next(name for name in ROLES if name != role)
            with self.subTest(role=role):
                self.run_shutdown(role, process=ROLES[other])

    def test_unrelated_process_is_not_signalled(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.run_shutdown(
                    role, process=("ghostship_inference.other", ()))

    def test_unresponsive_process_fails_shutdown(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.run_shutdown(role, ignore=True)


if __name__ == "__main__":
    unittest.main()
