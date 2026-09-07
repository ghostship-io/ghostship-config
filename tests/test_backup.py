import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BackupFailureTests(unittest.TestCase):
    def run_backup(self, failure):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bindir = root / "bin"
            bindir.mkdir()
            log = root / "commands"
            secret = root / "backup.env"
            secret.write_text("RESTIC_PASSWORD=test-only\n")
            script = (ROOT / "modules/self-hosted/backup.sh").read_text()
            script = script.replace(
                "/run/ghostship-maintenance.lock", str(root / "lock")
            )
            script = script.replace(
                "/run/ghostship-secrets/backup.env", str(secret)
            )
            script = script.replace(
                "/var/lib/ghostship-backup", str(root / "state")
            )
            script = script.replace(
                "/var/cache/ghostship-backup", str(root / "cache")
            )
            script = script.replace(
                "/var/lib/ghostship-cloudflare", str(root / "cloudflare")
            )
            script = script.replace(
                "/var/lib/ghostship-dashboards", str(root / "dashboards")
            )
            script = script.replace("/run/current-system", str(root))
            for command in [
                "findmnt",
                "podman",
                "systemctl",
                "btrfs",
                "restic",
                "readlink",
            ]:
                stub = bindir / command
                stub.write_text(
                    f"#!{shutil.which('bash')}\n"
                    "name=${0##*/}\n"
                    'printf "%s %s\\n" "$name" "$*" >> "$BACKUP_TEST_LOG"\n'
                    'case "$name:$1" in\n'
                    '  findmnt:*) [ "$BACKUP_TEST_FAILURE" != nas ] || exit 1; case "$*" in *--target*) echo / ;; esac ;;\n'
                    "  podman:inspect)\n"
                    '    case "$*" in\n'
                    "      *Healthcheck.Interval*) echo 30000000000 ;;\n"
                    "      *HealthcheckOnFailureAction*) echo kill ;;\n"
                    '      *State.Paused*) [ -f "$BACKUP_TEST_LOG.$2.paused" ] && echo true || echo false ;;\n'
                    "      *) echo true ;;\n"
                    "    esac ;;\n"
                    '  podman:pause) touch "$BACKUP_TEST_LOG.$2.paused" ;;\n'
                    "  podman:exec) exit 1 ;;\n"
                    '  btrfs:subvolume) case "$*" in "subvolume show /srv") [ "$BACKUP_TEST_FAILURE" != root ] ;; "subvolume show /") [ "$BACKUP_TEST_FAILURE" = root ] ;; *) exit 1 ;; esac ;;\n'
                    "  *) exit 0 ;;\n"
                    "esac\n"
                )
                stub.chmod(0o755)
            result = subprocess.run(
                ["bash", "-c", script, "backup-test", "backup"],
                env={
                    **os.environ,
                    "PATH": f"{bindir}:{os.environ['PATH']}",
                    "BACKUP_TEST_LOG": str(log),
                    "BACKUP_TEST_FAILURE": failure,
                },
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("test-only", result.stdout + result.stderr)
            return log.read_text()

    def test_missing_nas_never_pauses_apps_or_runs_restic(self):
        log = self.run_backup("nas")
        self.assertNotIn("podman", log)
        self.assertNotIn("restic", log)

    def test_dump_failure_resumes_same_containers_and_health_policy(self):
        log = self.run_backup("dump")
        for app in ["romm", "grimmory"]:
            self.assertIn(f"podman pause {app}", log)
            self.assertIn(f"podman unpause {app}", log)
            self.assertIn(f"--health-on-failure=kill {app}", log)
        self.assertNotIn("systemctl start", log)
        self.assertNotIn("restic", log)

    def test_declared_root_layout_is_accepted_before_quiescing(self):
        log = self.run_backup("root")
        self.assertIn("btrfs subvolume show /", log)
        self.assertIn("podman pause romm", log)
        self.assertIn("podman unpause romm", log)
