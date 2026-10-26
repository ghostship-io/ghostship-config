"""The served Go coordinator reads current model evidence from read-only mounts."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COORDINATOR = (ROOT / "modules/self-hosted/github-engineering.nix").read_text()
CHECKS = (ROOT / "checks.nix").read_text()
ACL_SCRIPT_PATH = ROOT / "modules/self-hosted/model-evidence-acl.sh"
ACL_SCRIPT = ACL_SCRIPT_PATH.read_text()
PROFILE = (
    ROOT / "modules/self-hosted/apparmor/ghostship-go-coordinator.profile"
).read_text()


class GoCoordinatorModelEvidenceTests(unittest.TestCase):
    def test_the_canonical_sources_are_mounted_read_only(self):
        self.assertIn('host = "/var/lib/ghostship-ai-usage";', COORDINATOR)
        self.assertIn(
            'host = "${t3Home}/.local/state/ghostship/model-evidence";', COORDINATOR
        )
        for name in ("modelRouting", "modelOutcomes"):
            self.assertIn(
                f'"${{{name}.host}}:${{{name}.mount}}:ro,noexec,nosuid,nodev"',
                COORDINATOR,
            )

    def test_the_service_is_told_the_file_inside_each_mount(self):
        self.assertIn('mount = "/run/ghostship-model-routing";', COORDINATOR)
        self.assertIn('file = "routing.json";', COORDINATOR)
        self.assertIn('mount = "/run/ghostship-model-evidence";', COORDINATOR)
        self.assertIn('file = "model-evidence.jsonl";', COORDINATOR)
        self.assertIn(
            'GHOSTSHIP_MODEL_RANKINGS_PATH = "${modelRouting.mount}/${modelRouting.file}"',
            COORDINATOR,
        )
        self.assertIn(
            'GHOSTSHIP_MODEL_EVIDENCE_PATH = "${modelOutcomes.mount}/${modelOutcomes.file}"',
            COORDINATOR,
        )

    def test_the_flake_check_pins_the_live_paths_and_the_directory_acl(self):
        self.assertIn('modelRoutingHost = "/var/lib/ghostship-ai-usage";', CHECKS)
        self.assertIn(
            'modelOutcomesHost = "/srv/apps/t3code/home/.local/state/ghostship/model-evidence";',
            CHECKS,
        )
        self.assertIn(
            "goCoordinator.environment.GHOSTSHIP_MODEL_RANKINGS_PATH", CHECKS
        )
        self.assertIn("goCoordinator.environment.GHOSTSHIP_MODEL_EVIDENCE_PATH", CHECKS)
        self.assertIn("u:62033:rx", CHECKS)

    def test_a_rewrite_reapplies_the_read_acl_without_a_restart(self):
        self.assertIn("systemd.services.ghostship-model-evidence-acl", COORDINATOR)
        self.assertIn("systemd.paths.ghostship-model-evidence-acl", COORDINATOR)
        self.assertIn('Unit = "ghostship-model-evidence-acl.service";', COORDINATOR)
        self.assertIn("PathModified = modelOutcomes.host;", COORDINATOR)
        self.assertIn("model-evidence-acl.sh", COORDINATOR)
        self.assertIn("u:62033:r,m::r", ACL_SCRIPT)

    @unittest.skipUnless(
        shutil.which("setfacl") and shutil.which("getfacl") and shutil.which("bash"),
        "requires POSIX ACL tools",
    )
    def test_a_ledger_created_after_startup_regains_read_access(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "model-evidence"
            work.mkdir()
            prepared = subprocess.run(
                ["setfacl", "-m", "d:u:62033:rX,d:m::r", str(work)],
                capture_output=True, text=True,
            )
            if prepared.returncode != 0:
                self.skipTest("filesystem does not support POSIX ACLs")
            ledger = work / "model-evidence.jsonl"
            ledger.write_text('{"row":1}\n')
            ledger.chmod(0o600)
            before = subprocess.run(
                ["getfacl", "-c", "--absolute-names", str(ledger)],
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertTrue(
                any(line.startswith("user:62033:") for line in before.splitlines()),
                "the inherited read entry is missing",
            )
            self.assertIn("mask::---", before)
            subprocess.run(
                ["bash", str(ACL_SCRIPT_PATH), str(ledger), shutil.which("setfacl")],
                check=True,
            )
            after = subprocess.run(
                ["getfacl", "-c", "--absolute-names", str(ledger)],
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertRegex(after, r"(?m)^user:62033:r")
            self.assertRegex(after, r"(?m)^mask::r")

    def test_the_apparmor_allowlist_covers_both_mounts(self):
        self.assertIn("/run/ghostship-model-routing/** r,", PROFILE)
        self.assertIn("/run/ghostship-model-evidence/** r,", PROFILE)


if __name__ == "__main__":
    unittest.main()
