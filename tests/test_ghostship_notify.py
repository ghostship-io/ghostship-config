"""ghostship-notify: one deduplicated publish per state, never suppressing a failed one."""
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "ghostship_notify", Path(__file__).resolve().parents[1] / "modules/self-hosted/ghostship-notify.py")
notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notify)


class NotifyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        secret = root / 'monitoring.env'
        secret.write_text("NTFY_PUBLISH_PASSWORD='pw'\n")
        self.received = []
        self.status = 200
        for name, value in (('STATE_DIR', root / 'state'), ('SECRETS', str(secret)),
                            ('INCIDENTS', str(root / 'incidents'))):
            patcher = mock.patch.object(notify, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server = mock.patch.object(notify, 'server', return_value='https://ntfy.invalid')
        server.start()
        self.addCleanup(server.stop)
        transport = mock.patch.object(notify.urllib.request, 'urlopen', side_effect=self.publish)
        transport.start()
        self.addCleanup(transport.stop)

    def publish(self, request, **_kwargs):
        self.received.append((request.get_header('Authorization'), json.loads(request.data)))
        if self.status != 200:
            raise notify.urllib.error.HTTPError(request.full_url, self.status, 'fixture failure', {}, None)
        return mock.MagicMock()

    def test_incident_only_requires_durable_spool_and_retries_with_same_event_identity(self):
        """An unavailable spool or failed fsync must never acknowledge the handoff."""
        with tempfile.TemporaryDirectory() as tmp:
            spool = Path(tmp) / "incidents"
            base = ["--topic", "operations", "--source", "newsletter", "--title", "failure",
                    "--dedupe", "newsletter-runtime", "--incident-only", "--incident-id", "episode-1", "m"]
            with mock.patch.object(notify, "INCIDENTS", str(spool)), \
                 mock.patch.object(notify, "server", side_effect=AssertionError("ntfy must be independent")):
                self.assertEqual(notify.main(base), 1)
                spool.mkdir()
                real_fsync = os.fsync

                def fail_directory_sync(fd):
                    if stat.S_ISDIR(os.fstat(fd).st_mode):
                        raise OSError("injected directory persistence failure")
                    return real_fsync(fd)

                with mock.patch.object(notify.os, "fsync", side_effect=OSError("injected file persistence failure")):
                    self.assertEqual(notify.main(base), 1)
                self.assertEqual(list(spool.iterdir()), [])
                with mock.patch.object(notify.os, "fsync", side_effect=fail_directory_sync):
                    self.assertEqual(notify.main(base), 1)
                (first,) = spool.glob("*.json")
                first.unlink()  # Consumer can ingest before the lost acknowledgement is retried.
                self.assertEqual(notify.main(base), 0)
                (retry,) = spool.glob("*.json")
                self.assertEqual(first.name, retry.name)
                self.assertEqual(retry.stat().st_mode & 0o777, 0o640)
                self.assertEqual(list(spool.glob("*.tmp")), [])

    def test_dedupe_publishes_each_state_once_and_retries_after_a_failed_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / "monitoring.env"
            secrets.write_text("NTFY_PUBLISH_PASSWORD='pw'\n")
            notify.SECRETS, notify.STATE_DIR = str(secrets), Path(tmp) / "state"
            base = ["--topic", "security", "--priority", "4", "--source", "sshd", "--dedupe", "k", "--title", "t"]
            self.status = 500
            self.assertEqual(notify.main(base + ["m"]), 1)
            self.status = 200
            for argv in (base, base, base + ["--state", "resolved"]):
                self.assertEqual(notify.main(argv + ["m"]), 0)
            self.assertEqual([b["tags"][:2] for _, b in self.received],
                             [["sshd", "firing"], ["sshd", "firing"], ["sshd", "resolved"]])
            self.assertEqual(self.received[-1][1]["topic"], "security")
            self.assertTrue(self.received[-1][0].startswith("Basic "))

    def test_incident_reaches_the_coordinator_spool_even_when_ntfy_is_down(self):
        """Defect: an ntfy outage drops the repair handoff, or a resolved alert starts a repair thread."""
        with tempfile.TemporaryDirectory() as tmp:
            secrets, spool = Path(tmp) / "monitoring.env", Path(tmp) / "incidents"
            secrets.write_text("NTFY_PUBLISH_PASSWORD='pw'\n")
            spool.mkdir()
            notify.SECRETS, notify.STATE_DIR, notify.INCIDENTS = str(secrets), Path(tmp) / "state", str(spool)
            base = ["--topic", "operations", "--source", "systemd", "--incident", "--dedupe", "x.service",
                    "--title", "Service x.service failed"]
            self.status = 500
            self.assertEqual(notify.main(base + ["exit 1"]), 1)
            self.status = 200
            self.assertEqual(notify.main(base + ["--state", "resolved", "ok"]), 0)
            (queued,) = [json.loads(path.read_text()) for path in spool.iterdir()]
            self.assertEqual((queued["key"], queued["title"], queued["message"]),
                             ("x.service", "Service x.service failed", "exit 1"))


if __name__ == "__main__":
    unittest.main()
