"""Exercise shutdown with real process identities, signals and exit statuses."""

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


source = Path(__file__).resolve().parents[1] / "modules/self-hosted/inference-scheduler-stop.py"
spec = importlib.util.spec_from_file_location("scheduler_stop", source)
scheduler_stop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduler_stop)


class SchedulerStopTest(unittest.TestCase):
    def test_already_exited_attachment_with_unset_mainpid_is_a_noop(self):
        for arguments in ([], [""]):
            result = subprocess.run(
                [sys.executable, str(source), "/unused/podman", *arguments],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def run_shutdown(self, exit_status=0, module="ghostship_inference", ignore=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / module
            package.mkdir()
            (package / "__init__.py").touch()
            (package / "cli.py").write_text(
                "import signal,time\nfrom pathlib import Path\n"
                + ("signal.signal(signal.SIGTERM,signal.SIG_IGN)\n" if ignore else
                   f"signal.signal(signal.SIGTERM,lambda *_:exit({exit_status}))\n")
                + "Path('ready').touch()\nwhile True: time.sleep(1)\n"
            )
            attachment = subprocess.Popen(
                [sys.executable, "-c",
                 "import subprocess,sys; "
                 "p=subprocess.Popen([sys.executable,'-m',sys.argv[1]+'.cli','serve']); "
                 "print(p.pid,flush=True); sys.exit(p.wait())", module],
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
                if module != "ghostship_inference":
                    with self.assertRaisesRegex(RuntimeError, "found 0"):
                        scheduler_stop.stop(str(podman), attachment.pid, timeout=1)
                    self.assertIsNone(attachment.poll())
                    os.kill(worker, 0)
                elif ignore:
                    with self.assertRaises(TimeoutError):
                        scheduler_stop.stop(str(podman), attachment.pid, timeout=0.1)
                    self.assertIsNone(attachment.poll())
                else:
                    scheduler_stop.stop(str(podman), attachment.pid, timeout=5)
                    self.assertEqual(attachment.wait(timeout=1), exit_status)
            finally:
                if attachment.poll() is None:
                    os.kill(worker, signal.SIGKILL)
                    attachment.wait(timeout=5)
                attachment.stdout.close()

    def test_orderly_stop_waits_for_worker_and_attachment(self):
        self.run_shutdown()

    def test_real_exit_one_is_preserved(self):
        self.run_shutdown(exit_status=1)

    def test_unrelated_process_is_not_signalled(self):
        self.run_shutdown(module="unrelated")

    def test_unresponsive_scheduler_fails_shutdown(self):
        self.run_shutdown(ignore=True)
